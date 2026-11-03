# ✦ QuizLens: Transparent AI Quiz & Exam Solver HUD

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.13%20%7C%203.14-3776AB?style=flat&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?style=flat&logo=windows&logoColor=white)
![AI Providers](https://img.shields.io/badge/Engines-Ollama%20%7C%20Gemini%20%7C%20Qwen-6366F1?style=flat)
![Stealth](https://img.shields.io/badge/UI-Ghost%20HUD%20(No%20Taskbar)-10B981?style=flat)

**An ultra-minimalist, transparent desktop HUD designed to overlay quiz questions, instantly classify MCQ vs. Free-response (Typing), extract the correct answer, and auto-copy it to your clipboard.**

[Features](#-key-features) • [Screenshots](#-screenshots--showcase) • [Tested Models](#-tested-models--hardware-benchmarks) • [Installation](#-installation--prerequisites) • [Usage](#-usage--shortcuts) • [Roadmap](#-what-to-do-next-roadmap)

</div>

---

## 📸 Live Demonstrations

| Free-Response / Definition (`[TYPING]`) | Multiple-Choice / Verification (`[MCQ]`) |
|:---:|:---:|
| ![Typing Answer](assets/demo_typing_solve.png) | ![MCQ Answer](assets/demo_mcq_solve.png) |
| *Instantly identifies free-response questions and outputs the clean answer ready to paste.* | *Extracts the correct option letter, option text, and concise 1-sentence verification.* |

---

## ⚡ Key Features

- **🔲 Minimalist 200×200 Square HUD**:
  Floating compact box that occupies under 5% of your screen estate, keeping 95% of its area reserved for the answer.
- **👁️ Taskbar-Invisible (True Stealth)**:
  Uses Windows Win32 API `WS_EX_TOOLWINDOW` to completely omit the application icon from the Windows Taskbar and Alt+Tab pager.
- **🧠 MCQ vs. Typing Auto-Differentiation**:
  Automatically analyzes whether a question has multiple-choice options (`A, B, C, D`, radio buttons, checkboxes) or is a free-response / definition question requiring an input string.
- **📋 Auto-Copy & 1-Click Clipboard**:
  Answers are instantly placed on your Windows system clipboard the moment they are solved. Clicking anywhere on the answer re-copies it.
- **👻 Ghost Mode & Deep Opacity**:
  Base transparency is 35% monochrome (adjustable from 10% to 85%), with an optional Ghost Mode that renders the background completely 100% invisible so only clean text floats over your window.
- **🔌 Tri-Engine Multi-LLM Architecture**:
  Seamlessly switch between **Ollama (100% offline local)**, **Google Gemini (cloud speed)**, and **Alibaba Qwen (frontier reasoning)** with one click in the Settings modal (`⚙`).

---

## 🧪 Tested Models & Hardware Benchmarks

All models below were tested directly on a real Windows workstation:
- **Processor**: 13th Gen Intel® Core™ i5-1334U (10 cores, 12 threads)
- **RAM**: 16 GB DDR4/DDR5
- **GPU**: Intel® Iris® Xe Graphics (Integrated)

| Model | Provider | Status | Benchmark & Analysis |
|---|---|---|---|
| **`llava:latest` (4.7 GB)** | **Ollama (Local)** | **✅ Recommended (Local)** | **Highest accuracy for local offline use.** Correctly distinguishes MCQ vs. Typing, follows strict JSON schemas, and outputs clean answers. Execution on CPU takes ~45–60s per question. |
| **`gemini-3.8-flash`** | **Google Gemini (Cloud)** | **⚡ Recommended (Speed)** | **Sub-second latency (~0.8s)**. World-class accuracy on university assessments, zero CPU or battery impact, perfect JSON adherence. |
| **`qwen-vl-max`** | **Alibaba Qwen (Cloud)** | **✅ Supported** | Excellent OCR accuracy on complex diagrams, code snippets, and mathematical formulas via DashScope API. |
| **`moondream:latest` (1.7 GB)** | **Ollama (Local)** | **⚠️ Limited** | Fast on CPU (~3s), but restricted to basic image captioning. Fails at structured exam logic and often re-echoes the question. |
| **`llama3.2-vision` (7.8 GB)** | **Ollama (Local)** | **❌ Incompatible (CPU)** | Fails with `unknown model architecture: 'mllama'`. Ollama's Windows CPU runner currently lacks CPU kernel support for the `mllama` vision architecture. |

---

## 🛠️ Installation & Prerequisites

### 1. Prerequisites
- **Windows 10 / 11**
- **Python 3.10+** (Tested and verified on Python 3.10, 3.13, and 3.14)

### 2. Clone the Repository
```bash
git clone https://github.com/saffronsarb/quizlens-overlay.git
cd quizlens-overlay
```

### 3. Install Python Dependencies
```powershell
pip install -r requirements.txt
```

*(Optional: For local offline inference, install [Ollama](https://ollama.com) via `winget install Ollama.Ollama` and pull LLaVA via `ollama run llava`).*

---

## 🚀 Usage & Shortcuts

### Launching the Application

- **Headless Stealth Mode (No Command Prompt Window)**:
  Double-click [**`run_silent.bat`**](file:///run_silent.bat) (runs silently in the background via `pythonw.exe`).
- **Standard Mode (With Console)**:
  Double-click [**`run.bat`**](file:///run.bat).

### Keyboard Shortcuts

| Shortcut | Action | Description |
|---|---|---|
| **`Alt+S`** or `Ctrl+Alt+S` | **Snip Region** | Freezes screen to drag a rectangle over any question. |
| **`Ctrl+V`** or `Ctrl+Alt+V` | **Clipboard Solve** | Solves image directly from clipboard (e.g. after pressing `Win+Shift+S`). |
| **`Alt+F`** or `Ctrl+Alt+F` | **Fullscreen Solve** | Instantly captures entire screen and solves question. |
| **`Click on Answer`** | **One-Click Copy** | Copies the cleanest answer string back to clipboard. |
| **`Ctrl+Alt+H`** | **Boss-Key Toggle** | Instantly hides or shows the overlay window. |
| **`Right-Click`** | **Context Menu** | Opens quick menu for Settings, Snip, Copy, or Exit. |
| **`Esc`** or **`✕`** | **Close HUD** | Safely saves window coordinates and closes. |

---

## ⚙️ Configuration (`config.json`)

Settings can be changed visually through the **⚙ (Gear)** dialog, or edited manually in [`config.json`](file:///config.json):

```json
{
  "provider": "ollama",
  "api_key": "",
  "ollama_base_url": "http://localhost:11434/v1",
  "ollama_model": "llava",
  "qwen_base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
  "qwen_model": "qwen-vl-max",
  "gemini_model": "gemini-3.8-flash",
  "model": "llava",
  "opacity": 0.35,
  "font_size": 8,
  "auto_copy": true,
  "always_on_top": true,
  "glass_mode": false,
  "hide_from_taskbar": true,
  "window_width": 200,
  "window_height": 200
}
```

> **Security Note**: Never commit your real API keys to public source control. Keep keys in your local `config.json` or pass them via environment variables (`GEMINI_API_KEY`, `DASHSCOPE_API_KEY`, `OLLAMA_API_KEY`).

---

## 🗺️ What to Do Next (Roadmap)

- [ ] **Local Fast OCR Pipeline**: Integrate Tesseract / RapidOCR to extract question text locally before passing to language-only models (reducing local CPU solve time from 50s to ~2s).
- [ ] **System Tray Integration**: Add a system tray icon with quick toggle, profile switcher, and hotkey binder.
- [ ] **History & Log Export**: Optional export of question-and-answer pairs into Markdown or CSV study guides.
- [ ] **Multi-Monitor Coordinate Fixes**: Enhanced DPI coordinate translation across mixed-DPI multi-monitor gaming/testing rigs.
- [ ] **Whisper Speech Mode**: Auto-listen for voice quizzes and oral exams.

---

## 📄 License

Distributed under the [MIT License](LICENSE).
