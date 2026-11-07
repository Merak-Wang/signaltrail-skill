/*
MIT License

Copyright (c) 2023-2026 The ggml authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/
// Based on ggml-org/llama.cpp b11981 tools/tts/tts.cpp (MIT).
#include "arg.h"
#include "chat.h"
#include "common.h"
#include "llama.h"
#include "log.h"
#include "mtmd-helper.h"
#include "mtmd.h"
#include "sampling.h"

#include "nlohmann/json.hpp"
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>

static std::string diagnostic;
static std::mutex diagnostic_mutex;
// 汇集本次原生诊断，回执同时提供 GPU 加载和逐段帧数。
static void worker_log(enum ggml_log_level, const char *text, void *) {
  std::lock_guard<std::mutex> lock(diagnostic_mutex);
  diagnostic += text;
  std::fputs(text, stderr);
}
struct tts_timings {
  int64_t t_start_us = ggml_time_us();
  int64_t t_last_us = t_start_us;

  void report(int n_frames) {
    const int64_t t_now_us = ggml_time_us();
    if (t_now_us - t_last_us < 2000000) {
      return;
    }
    t_last_us = t_now_us;
    const double t_elapsed_s = (t_now_us - t_start_us) / 1e6;
    const double fps = t_elapsed_s > 0 ? n_frames / t_elapsed_s : 0.0;
    LOG_INF("frames generated: %d, speed: %.2f frames/s\n", n_frames, fps);
  }
};

static void print_usage(int, char **argv) {
  LOG("\nexample usage:\n");
  LOG("\n    %s -m backbone.gguf -mm mmproj.gguf -p \"text to speak\" -o "
      "output.wav",
      argv[0]);
  LOG("\n    %s -hf user/model -p \"text to speak\" -o output.wav\n", argv[0]);
  LOG("\nnote: --tts-lang, --tts-voice and --tts-speaker-file may not be "
      "supported in all models");
  LOG("\n      use -n to limit the output length");
  LOG("\n      see tts/README.md for per-model usage notes");
  LOG("\n\n");
}

int main(int argc, char **argv) {
  common_params params;

  common_init();

  if (!common_params_parse(argc, argv, params, LLAMA_EXAMPLE_TTS,
                           print_usage)) {
    return 1;
  }

  llama_log_set(worker_log, nullptr);
  ggml_log_set(worker_log, nullptr);
  mtmd_helper_log_set(worker_log, nullptr);

  if (params.mmproj.path.empty()) {
    LOG_ERR("no mmproj provided, use --mmproj\n");
    return 1;
  }

  params.embedding = true;

  llama_backend_init();
  llama_numa_init(params.numa);

  auto llama_init = common_init_from_params(params);
  llama_model *model = llama_init->model();
  llama_context *lctx = llama_init->context();
  common_sampler *smpl = llama_init->sampler(0);
  if (!model || !lctx) {
    LOG_ERR("failed to init model/context\n");
    return 1;
  }

  mtmd_context_params mtmd_params = mtmd_context_params_default();
  mtmd_params.use_gpu = params.mmproj_use_gpu;
  mtmd_params.device = params.mmproj_device;
  mtmd::context_ptr mctx(
      mtmd_init_from_file(params.mmproj.path.c_str(), model, mtmd_params));
  if (!mctx) {
    LOG_ERR("failed to load mmproj %s\n", params.mmproj.path.c_str());
    return 1;
  }
  if (mtmd_gen_audio_get_info(mctx.get()).type == MTMD_GEN_AUDIO_TYPE_NONE) {
    LOG_ERR("mmproj does not support audio generation\n");
    return 1;
  }

  mtmd::bitmap_ptr speaker_bitmap;
  if (!params.tts_speaker_file.empty()) {
    auto wrapper = mtmd_helper_bitmap_init_from_file(
        mctx.get(), params.tts_speaker_file.c_str(), false,
        mtmd_helper_init_opt_default());
    if (!wrapper.bitmap) {
      LOG_ERR("failed to load speaker file %s\n",
              params.tts_speaker_file.c_str());
      return 1;
    }
    speaker_bitmap.reset(wrapper.bitmap);
  }

  auto tmpls = common_chat_templates_init(model, "");
  mtmd_helper::gen_audio gen;
  gen.init(lctx, mctx.get());
  std::cout
      << nlohmann::json({{"ready", true}, {"diagnostic", diagnostic}}).dump()
      << std::endl;
  std::string request_line;
  // 每段清空生成状态，保留模型、投影器与参考音频。
  while (std::getline(std::cin, request_line)) {
    try {
      diagnostic.clear();
      auto request = nlohmann::json::parse(request_line);
      std::ifstream input(request.at("text_file").get<std::string>());
      std::ostringstream text;
      text << input.rdbuf();
      params.prompt = text.str();
      params.out_file = request.at("output").get<std::string>();
      params.tts_lang = request.value("language", "zh");
      gen.reset();
      llama_memory_clear(llama_get_memory(lctx), true);
      common_sampler_reset(smpl);
      std::string prompt = common_chat_get_tts_prompt(
          tmpls.get(), params.prompt, params.tts_lang, params.tts_voice);
      if (prompt.empty())
        prompt = params.prompt;
      mtmd_helper_gen_audio_inp inp = mtmd_helper_gen_audio_inp_default();
      inp.seq_id = 0;
      inp.prompt = prompt.c_str();
      inp.prompt_len = prompt.size();
      inp.speaker_ref = speaker_bitmap.get();
      inp.lang = params.tts_lang.c_str();
      inp.voice = params.tts_voice.c_str();
      inp.top_k = params.sampling.top_k;
      inp.top_p = params.sampling.top_p;
      inp.seed = params.sampling.seed;

      if (gen.set_input(&inp) != 0) {
        LOG_ERR("set_input failed\n");
        return 1;
      }

      const int64_t t_prompt_start_us = ggml_time_us();

      for (;;) {
        int32_t ret = gen.step_prompt(params.n_batch);
        if (ret < 0) {
          LOG_ERR("prompt processing failed\n");
          return 1;
        }
        if (ret == 0) {
          break;
        }
      }

      auto sample_semantic_code = [&]() -> llama_token {
        llama_token t = common_sampler_sample(smpl, lctx, -1);
        common_sampler_accept(smpl, t, true);
        return t;
      };

      const int max_new = params.n_predict > 0 ? params.n_predict : 512;
      int n_frames = 0;
      llama_token sampled = sample_semantic_code();
      const float *h_state = llama_get_embeddings_ith(lctx, -1);

      tts_timings timings;
      const int64_t t_gen_start_us = ggml_time_us();

      bool stop = false;
      while (!stop && n_frames < max_new) {
        const float *h_next = nullptr;

        if (gen.step_gen(sampled, h_state, &h_next, &stop) != 0) {
          LOG_ERR("step_gen failed at frame %d\n", n_frames);
          return 1;
        }
        if (!h_next) {
          break; // stopped without generating a frame
        }

        n_frames++;
        h_state = h_next;
        sampled = sample_semantic_code();
        timings.report(n_frames);
      }
      const double t_gen_s = (ggml_time_us() - t_gen_start_us) / 1e6;

      int32_t sample_rate = 0;
      const char *data = nullptr;
      size_t data_len = 0;
      int64_t n_samples = 0;
      const int64_t t_wav_start_us = ggml_time_us();
      if (gen.get_output(&sample_rate, &data, &data_len, &n_samples) != 0) {
        LOG_ERR("get_output failed\n");
        return 1;
      }
      const double t_wav_s = (ggml_time_us() - t_wav_start_us) / 1e6;

      LOG_INF("generated %d frames, %zu bytes of WAV audio (%d Hz)\n", n_frames,
              data_len, sample_rate);

      const double t_prompt_s = (t_gen_start_us - t_prompt_start_us) / 1e6;
      const double t_total_s = t_prompt_s + t_gen_s + t_wav_s;
      const double audio_s =
          sample_rate > 0 ? (double)n_samples / sample_rate : 0.0;
      LOG_INF("timings: prompt eval %.2fs + generation %.2fs + vocoder %.2fs = "
              "total %.2fs\n",
              t_prompt_s, t_gen_s, t_wav_s, t_total_s);
      LOG_INF(
          "         output audio = %.2fs (audio time = %.2fx process time)\n",
          audio_s, t_total_s > 0 ? audio_s / t_total_s : 0.0);
      FILE *f = fopen(params.out_file.c_str(), "wb");
      if (!f) {
        LOG_ERR("failed to open %s\n", params.out_file.c_str());
        return 1;
      }
      fwrite(data, 1, data_len, f);
      fclose(f);
      LOG_INF("wrote %s\n", params.out_file.c_str());

      std::cout << nlohmann::json({{"ok", true},
                                   {"output", params.out_file},
                                   {"frames", n_frames},
                                   {"diagnostic", diagnostic + "\ngenerated " +
                                                      std::to_string(n_frames) +
                                                      " frames\n"}})
                       .dump()
                << std::endl;
    } catch (const std::exception &error) {
      std::cout
          << nlohmann::json({{"ok", false}, {"error", error.what()}}).dump()
          << std::endl;
    }
  }
  return 0;
}
