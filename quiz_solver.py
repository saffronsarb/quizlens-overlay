import io
import json
import re
import base64
import requests
from PIL import Image

SYSTEM_INSTRUCTION = """You are an ultra-fast, high-precision quiz and exam assistant.
You will receive an image containing a question from a quiz, test, or assessment on a computer screen.

Your objectives:
1. DETERMINE THE QUESTION TYPE:
   - "MCQ": Multiple-choice question with explicit options printed in the image (e.g., A, B, C, D; radio buttons; checkboxes).
   - "TYPING": Free-response or definition question where NO multiple-choice options are provided in the image (e.g., short answer, definition, fill-in-the-blank, numeric calculation, exact phrase).

2. DETERMINE THE EXACT CORRECT ANSWER:
   - If MCQ:
     * Identify the correct option from the options visible in the image.
     * Set 'correct_answer' to the option letter AND option text from the image.
     * Set 'copy_text' to the exact option text ready for clipboard paste.
     * NEVER invent options that are not shown in the image.
   - If TYPING:
     * Answer the question directly with the most accurate, concise definition, fact, or value.
     * Keep it free of preamble like "The answer is" or filler phrases.
     * Set 'correct_answer' and 'copy_text' to this exact answer string.

3. PROVIDE CONCISE JUSTIFICATION:
   - Provide a 1-sentence quick explanation verifying why this answer is correct.

You MUST respond strictly with valid JSON conforming to this schema:
{
  "type": "MCQ" | "TYPING",
  "question_summary": "Concise summary of the question identified",
  "correct_answer": "Direct answer string",
  "copy_text": "Cleanest string ready for clipboard paste",
  "explanation": "1-sentence verification of why this answer is correct"
}
"""

class QuizSolver:
    def __init__(
        self,
        provider: str = "ollama",
        api_key: str = "",
        model: str = "llama3.2-vision",
        base_url: str = "http://localhost:11434/v1"
    ):
        self.provider = provider.lower()
        self.api_key = api_key.strip()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.gemini_client = None

        if self.provider == "gemini" and self.api_key:
            self._init_gemini()

    def _init_gemini(self):
        try:
            from google import genai
            self.gemini_client = genai.Client(api_key=self.api_key)
        except Exception as e:
            self.gemini_client = None
            print(f"Gemini client init error: {e}")

    def update_credentials(
        self,
        provider: str,
        api_key: str,
        model: str,
        base_url: str = ""
    ):
        self.provider = provider.lower()
        self.api_key = api_key.strip()
        self.model = model
        if base_url:
            self.base_url = base_url.rstrip("/")
        elif self.provider == "ollama":
            self.base_url = "http://localhost:11434/v1"
        elif self.provider == "qwen":
            self.base_url = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

        if self.provider == "gemini" and self.api_key:
            self._init_gemini()

    def test_connection(self) -> tuple[bool, str]:
        """Verify API key/server connectivity for the selected provider."""
        if self.provider == "ollama":
            return self._test_ollama()
        elif self.provider == "qwen":
            return self._test_qwen()
        elif self.provider == "gemini":
            return self._test_gemini()
        else:
            return False, f"Unknown provider: {self.provider}"

    def _test_ollama(self) -> tuple[bool, str]:
        """Test connection to local or remote Ollama server."""
        base = self.base_url.rstrip("/")
        clean_base = base[:-3] if base.endswith("/v1") else base
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # 1. First probe Ollama native /api/tags
        try:
            resp = requests.get(f"{clean_base}/api/tags", headers=headers, timeout=4)
            if resp.status_code == 200:
                models_data = resp.json().get("models", [])
                model_names = [m.get("name") for m in models_data if isinstance(m, dict)]
                if self.model and any(self.model in name for name in model_names):
                    return True, f"Ollama online! '{self.model}' ready."
                elif model_names:
                    return True, f"Ollama online! Available: {model_names[0]}"
                return True, "Ollama online! (No model pulled yet)"
        except requests.exceptions.ConnectionError:
            return False, f"Ollama not running at {clean_base}"
        except Exception:
            pass

        # 2. Probe OpenAI compatibility /v1/models
        try:
            v1_url = f"{clean_base}/v1/models"
            resp = requests.get(v1_url, headers=headers, timeout=4)
            if resp.status_code == 200:
                return True, "Ollama OpenAI endpoint online!"
        except requests.exceptions.ConnectionError:
            return False, f"Ollama not running at {clean_base}"
        except Exception as e:
            return False, f"Cannot connect: {str(e)[:40]}"

        return False, f"Ollama returned HTTP error from {clean_base}"

    def _test_qwen(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Qwen API key is missing."
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "Reply with OK"}],
            "max_tokens": 10
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=12)
            if resp.status_code == 200:
                return True, "Qwen API key is valid and active!"
            else:
                err_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                err_msg = err_data.get("message") or err_data.get("error", {}).get("message") or resp.text[:100]
                return False, f"Qwen error ({resp.status_code}): {err_msg}"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def _test_gemini(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Gemini API key is missing."
        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)
            resp = client.models.generate_content(
                model=self.model or "gemini-3.8-flash",
                contents="Reply with OK"
            )
            if resp and resp.text:
                return True, "Gemini API key is active!"
            return False, "No response from Gemini."
        except Exception as e:
            return False, f"Gemini error: {str(e)}"

    def solve_question(self, pil_image: Image.Image) -> dict:
        """Analyze image, classify question, and return structured answer."""
        # Convert image to RGB
        if pil_image.mode not in ("RGB", "L"):
            pil_image = pil_image.convert("RGB")

        if self.provider == "ollama":
            return self._solve_ollama(pil_image)
        elif self.provider == "qwen":
            return self._solve_qwen(pil_image)
        elif self.provider == "gemini":
            return self._solve_gemini(pil_image)
        else:
            return {"success": False, "error": f"Unknown provider: {self.provider}"}

    def _solve_ollama(self, pil_image: Image.Image) -> dict:
        """Solve using Ollama (supporting local or remote vision models)."""
        try:
            buffered = io.BytesIO()
            pil_image.save(buffered, format="JPEG", quality=90)
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

            base = self.base_url.rstrip("/")
            v1_url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            # Standard OpenAI Vision payload
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": SYSTEM_INSTRUCTION
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{img_b64}"
                                }
                            },
                            {
                                "type": "text",
                                "text": "Analyze this quiz/test image. If options A/B/C/D are printed, classify as MCQ. If NO options are visible, classify as TYPING and output the concise factual answer/definition. Output valid JSON."
                            }
                        ]
                    }
                ],
                "temperature": 0.1,
                "stream": False
            }

            clean_base = base[:-3] if base.endswith("/v1") else base

            try:
                resp = requests.post(v1_url, json=payload, headers=headers, timeout=200)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_text = data["choices"][0]["message"]["content"]
                    parsed_data = self._parse_json_response(raw_text)
                    return {
                        "success": True,
                        "type": parsed_data.get("type", "MCQ").upper(),
                        "question_summary": parsed_data.get("question_summary", "Question analyzed"),
                        "correct_answer": parsed_data.get("correct_answer", "No answer found"),
                        "copy_text": parsed_data.get("copy_text", parsed_data.get("correct_answer", "")),
                        "explanation": parsed_data.get("explanation", ""),
                        "raw": raw_text
                    }
            except requests.exceptions.ConnectionError:
                return {
                    "success": False,
                    "error": f"Ollama is offline ({clean_base} unreachable).\n\n"
                             f"• If local: Run 'ollama serve' in terminal\n"
                             f"• If remote: Check URL in Settings (⚙)\n"
                             f"• Or switch to Gemini/Qwen in Settings (⚙)"
                }
            except requests.exceptions.Timeout:
                return {
                    "success": False,
                    "error": "Ollama CPU processing timed out (>200s).\n\nRunning a 7B model on a laptop CPU is very slow. Switch to Gemini in Settings (⚙) for instant (<1s) answers!"
                }
            except Exception:
                pass

            # Fallback to Ollama native /api/chat
            native_url = f"{clean_base}/api/chat"
            native_payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": SYSTEM_INSTRUCTION
                    },
                    {
                        "role": "user",
                        "content": "Analyze this quiz/test image. If options A/B/C/D are printed, classify as MCQ. If NO options are visible, classify as TYPING and output the concise factual answer/definition. Output valid JSON.",
                        "images": [img_b64]
                    }
                ],
                "stream": False,
                "format": "json"
            }

            resp2 = requests.post(native_url, json=native_payload, headers=headers, timeout=200)
            if resp2.status_code == 200:
                data2 = resp2.json()
                raw_text = data2["message"]["content"]
                parsed_data = self._parse_json_response(raw_text)
                return {
                    "success": True,
                    "type": parsed_data.get("type", "MCQ").upper(),
                    "question_summary": parsed_data.get("question_summary", "Question analyzed"),
                    "correct_answer": parsed_data.get("correct_answer", "No answer found"),
                    "copy_text": parsed_data.get("copy_text", parsed_data.get("correct_answer", "")),
                    "explanation": parsed_data.get("explanation", ""),
                    "raw": raw_text
                }
            elif resp2.status_code == 404:
                return {"success": False, "error": f"Model '{self.model}' not found in Ollama.\nRun: ollama pull {self.model}"}

            return {"success": False, "error": f"Ollama error ({resp2.status_code}): {resp2.text[:80]}"}

        except requests.exceptions.ConnectionError:
            clean_base = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
            return {
                "success": False,
                "error": f"Ollama is offline ({clean_base} unreachable).\n\n"
                         f"• If local: Run 'ollama serve' in terminal\n"
                         f"• If remote: Check URL in Settings (⚙)\n"
                         f"• Or switch to Gemini/Qwen in Settings (⚙)"
            }
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "error": "Ollama timed out (>200s).\n\nRunning a 7B model on a laptop CPU is very slow.\nSwitch to Gemini in Settings (⚙) for instant (<1s) answers!"
            }
        except Exception as e:
            return {"success": False, "error": f"Ollama error: {str(e)[:80]}"}

    def _solve_qwen(self, pil_image: Image.Image) -> dict:
        """Solve using Qwen Vision (DashScope / OpenAI-compatible endpoint)."""
        if not self.api_key:
            return {"success": False, "error": "No Qwen API Key found. Open Settings (⚙) to enter it."}

        try:
            buffered = io.BytesIO()
            pil_image.save(buffered, format="JPEG", quality=90)
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

            url = f"{self.base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": SYSTEM_INSTRUCTION
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{img_b64}"
                                }
                            },
                            {
                                "type": "text",
                                "text": "Analyze this quiz/test screen capture. Determine if MCQ or TYPING question, find the correct answer, and output JSON strictly conforming to the schema."
                            }
                        ]
                    }
                ],
                "temperature": 0.1
            }

            resp = requests.post(url, json=payload, headers=headers, timeout=35)
            if resp.status_code != 200:
                err_text = resp.text[:120]
                try:
                    err_json = resp.json()
                    err_text = err_json.get("message") or err_json.get("error", {}).get("message") or err_text
                except Exception:
                    pass
                return {"success": False, "error": f"Qwen API error ({resp.status_code}): {err_text}"}

            data = resp.json()
            raw_text = data["choices"][0]["message"]["content"]
            parsed_data = self._parse_json_response(raw_text)

            return {
                "success": True,
                "type": parsed_data.get("type", "MCQ").upper(),
                "question_summary": parsed_data.get("question_summary", "Question analyzed"),
                "correct_answer": parsed_data.get("correct_answer", "No answer found"),
                "copy_text": parsed_data.get("copy_text", parsed_data.get("correct_answer", "")),
                "explanation": parsed_data.get("explanation", ""),
                "raw": raw_text
            }

        except Exception as e:
            return {"success": False, "error": f"Qwen processing error: {str(e)}"}

    def _solve_gemini(self, pil_image: Image.Image) -> dict:
        """Solve using Gemini API."""
        if not self.api_key:
            return {"success": False, "error": "No Gemini API Key found. Open Settings (⚙) to enter it."}

        try:
            from google import genai
            from google.genai import types

            if not self.gemini_client:
                self.gemini_client = genai.Client(api_key=self.api_key)

            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.1,
                response_mime_type="application/json"
            )

            prompt = (
                "Analyze this quiz/test screen capture. Determine if it is an MCQ or a TYPING question, "
                "find the correct answer, and return the structured JSON result."
            )

            response = self.gemini_client.models.generate_content(
                model=self.model or "gemini-3.8-flash",
                contents=[pil_image, prompt],
                config=config
            )

            raw_text = response.text or ""
            parsed_data = self._parse_json_response(raw_text)

            return {
                "success": True,
                "type": parsed_data.get("type", "MCQ").upper(),
                "question_summary": parsed_data.get("question_summary", "Question analyzed"),
                "correct_answer": parsed_data.get("correct_answer", "No answer found"),
                "copy_text": parsed_data.get("copy_text", parsed_data.get("correct_answer", "")),
                "explanation": parsed_data.get("explanation", ""),
                "raw": raw_text
            }

        except Exception as e:
            return {"success": False, "error": f"Gemini error: {str(e)}"}

    def _parse_json_response(self, text: str) -> dict:
        """Clean and extract structured data from model output."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            type_match = re.search(r'"type"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
            ans_match = re.search(r'"correct_answer"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
            copy_match = re.search(r'"copy_text"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
            expl_match = re.search(r'"explanation"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
            summ_match = re.search(r'"question_summary"\s*:\s*"([^"]+)"', text, re.IGNORECASE)

            ans = ans_match.group(1) if ans_match else text[:100]
            copy_txt = copy_match.group(1) if copy_match else ans

            return {
                "type": (type_match.group(1) if type_match else "MCQ").upper(),
                "question_summary": summ_match.group(1) if summ_match else "Extracted question",
                "correct_answer": ans,
                "copy_text": copy_txt,
                "explanation": expl_match.group(1) if expl_match else ""
            }
