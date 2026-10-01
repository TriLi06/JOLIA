# Third-Party Notices

The root [LICENSE](LICENSE) applies to JOLIA's original code under PolyForm Noncommercial 1.0.0. It does not replace the separate terms for third-party components listed here.

## Feather Icons

The inline SVG icon paths in `app/templates/base.html` are derived from Feather Icons.

Source: <https://github.com/feathericons/feather>
License: MIT

## Pico CSS 2.1.1

`app/templates/base.html` and `app/templates/login.html` load Pico CSS from jsDelivr. The CSS is fetched at runtime and is not stored in this repository.

Source: <https://github.com/picocss/pico>
License: MIT

## Third-Party MIT License Notices

Copyright (c) 2013-2023 Cole Bemis

Copyright (c) 2019-2024 Pico

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

## OpenCV.js 4.9.0

`docscan-pwa/public/opencv/opencv.js` is the official OpenCV.js 4.9.0 build downloaded from <https://docs.opencv.org/4.9.0/opencv.js>. Its SHA-256 is `4D7B85E2E12EA0BD088F491C311D620A45B53D1489B7F065B4492A230BDA243A`. No modifications were made to the downloaded file.

OpenCV 4.9.0 is licensed under Apache-2.0. The full upstream license is included in [LICENSE-OpenCV-4.9.0.txt](LICENSE-OpenCV-4.9.0.txt); the upstream license source is <https://github.com/opencv/opencv/blob/4.9.0/LICENSE>. No root `NOTICE` file exists in the upstream 4.9.0 tag.

`.gitattributes` prevents line-ending conversion for this asset. Include the current `LICENSE-OpenCV-4.9.0.txt` when distributing the repository or any source snapshot containing the OpenCV.js file.

## Dependency References

Python requirements and the PWA npm lockfile describe dependencies fetched by package managers; their source code is not vendored in this repository. They are not individually reproduced here. Before distributing a built PWA or container image, resolve that release's exact dependency graph and include the required notices and any separate model/data terms. A package manager's license metadata is an inventory aid, not by itself proof of compliance.

## Models and Runtime Downloads

JOLIA's source repository does not contain the model checkpoints listed below. The WSL installer and Docker build do cause model files to be downloaded to the user's machine. In particular, the OpenAI CLIP checkpoint is copied into the Docker image built from this repository; anyone publishing that image is redistributing the checkpoint and must satisfy its applicable terms. Ollama and Hugging Face tags may change, so verify the exact model revision and license before each binary/image release.

| Model / component | How it is obtained | License and release considerations |
| --- | --- | --- |
| `qwen2.5:1.5b` | Pulled by Ollama during setup | Apache-2.0. [Ollama model page](https://ollama.com/library/qwen2.5:1.5b) |
| `qwen2.5:7b` | Pulled by Ollama during setup | Apache-2.0. [Ollama model page](https://ollama.com/library/qwen2.5:7b) |
| `qwen2.5vl:3b` | Pulled by Ollama during setup | Apache-2.0 according to the current Ollama model page. Confirm the exact tag/revision and current terms. [Ollama model page](https://ollama.com/library/qwen2.5vl:3b) |
| `bge-m3` | Pulled by Ollama during setup | MIT, according to the upstream model card. [Model card](https://huggingface.co/BAAI/bge-m3) |
| `qwen2.5:3b` (optional alternative, not a default) | Only if selected manually | Qwen Research License. Its definition of non-commercial is limited to research or evaluation purposes; commercial use requires a separate license. Redistributors must include the agreement and required attribution notice. [Ollama model page](https://ollama.com/library/qwen2.5:3b) |
| `minicpm-v` (optional alternative, not a default) | Only if selected manually | Follow the MiniCPM Model License. The upstream model card says academic research is free and commercial use requires registration via its questionnaire. Confirm the exact tag/revision and current terms. [Ollama model page](https://ollama.com/library/minicpm-v), [upstream model card](https://huggingface.co/openbmb/MiniCPM-V-2_6) |
| OpenAI CLIP `ViT-B-32` checkpoint | Downloaded by `docker/download_clip_model.py` during the Docker image build | The OpenAI CLIP project is MIT-licensed; check the upstream license and model card for the exact checkpoint and retain applicable notices when distributing an image containing it. [License](https://github.com/openai/CLIP/blob/main/LICENSE), [model card](https://github.com/openai/CLIP/blob/main/model-card.md) |
| LAION `larger_clap_music` | Downloaded from Hugging Face when CLAP is first used | Apache-2.0, according to the upstream model card. The configured model can be changed. [Model card](https://huggingface.co/laion/larger_clap_music) |
| OpenAI Whisper model files | Downloaded when transcription first uses the selected Whisper model | The Whisper project is MIT-licensed. Verify and retain the upstream terms for the specific model files included in any distributed artifact. [License](https://github.com/openai/whisper/blob/main/LICENSE) |
| dlib 68-point face landmark model, used through `face-recognition` | Installed/downloaded with the face-recognition model package in the Docker build | The upstream dlib model notice says the 68-point model is trained on the iBUG 300-W dataset, whose terms exclude commercial use, and warns against use in commercial products without permission. Acknowledging this notice does not grant permission. [dlib model terms](https://github.com/davisking/dlib-models) |

These model terms are separate from JOLIA's PolyForm Noncommercial license and from the licenses of the libraries that load the models. The WSL installer's confirmation is an acknowledgment only; it does not grant additional rights, replace a required registration/license, or make a restricted model suitable for a use its own terms prohibit. Users and distributors must check the current terms for their own use and the exact model revisions. Do not distribute a built image containing a model unless its terms permit that distribution and all required notices are included.