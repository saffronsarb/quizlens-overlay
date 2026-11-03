import unittest
import json
from PIL import Image
from config_manager import load_config, save_config, DEFAULT_CONFIG
from quiz_solver import QuizSolver

class TestQuizLens(unittest.TestCase):
    def test_config_defaults(self):
        config = load_config()
        self.assertIn("opacity", config)
        self.assertIn("provider", config)
        self.assertIn("model", config)
        self.assertIn("font_size", config)
        self.assertIn("auto_copy", config)
        self.assertIn("ollama_base_url", config)
        self.assertIn("ollama_model", config)
        self.assertIn(config.get("provider"), ["ollama", "qwen", "gemini"])

    def test_qwen_json_parsing_mcq(self):
        solver = QuizSolver(provider="qwen", api_key="test_key")
        sample_json = """{
            "type": "MCQ",
            "question_summary": "What is the powerhouse of the cell?",
            "correct_answer": "B) Mitochondria",
            "copy_text": "Mitochondria",
            "explanation": "Mitochondria generate chemical energy."
        }"""
        parsed = solver._parse_json_response(sample_json)
        self.assertEqual(parsed["type"], "MCQ")
        self.assertEqual(parsed["correct_answer"], "B) Mitochondria")
        self.assertEqual(parsed["copy_text"], "Mitochondria")

    def test_qwen_json_parsing_typing(self):
        solver = QuizSolver(provider="qwen", api_key="test_key")
        sample_json = """{
            "type": "TYPING",
            "question_summary": "Water boiling point at 1 atm is ___ Celsius.",
            "correct_answer": "100",
            "copy_text": "100",
            "explanation": "Boiling point of water is 100 C."
        }"""
        parsed = solver._parse_json_response(sample_json)
        self.assertEqual(parsed["type"], "TYPING")
        self.assertEqual(parsed["correct_answer"], "100")
        self.assertEqual(parsed["copy_text"], "100")

    def test_ollama_json_parsing(self):
        solver = QuizSolver(provider="ollama", model="llama3.2-vision")
        sample_json = """{
            "type": "MCQ",
            "question_summary": "Which planet is closest to the sun?",
            "correct_answer": "A) Mercury",
            "copy_text": "Mercury",
            "explanation": "Mercury is the first planet from the Sun."
        }"""
        parsed = solver._parse_json_response(sample_json)
        self.assertEqual(parsed["type"], "MCQ")
        self.assertEqual(parsed["correct_answer"], "A) Mercury")
        self.assertEqual(parsed["copy_text"], "Mercury")

    def test_markdown_fence_cleaning(self):
        solver = QuizSolver(provider="ollama", api_key="")
        sample_md = """```json
        {
            "type": "MCQ",
            "question_summary": "Which planet is known as Red Planet?",
            "correct_answer": "C) Mars",
            "copy_text": "Mars",
            "explanation": "Mars has iron oxide."
        }
        ```"""
        parsed = solver._parse_json_response(sample_md)
        self.assertEqual(parsed["type"], "MCQ")
        self.assertEqual(parsed["correct_answer"], "C) Mars")

    def test_solver_provider_switch(self):
        # Start with Ollama
        solver = QuizSolver(provider="ollama", api_key="bearer_123", model="llama3.2-vision", base_url="http://localhost:11434/v1")
        self.assertEqual(solver.provider, "ollama")
        self.assertEqual(solver.base_url, "http://localhost:11434/v1")

        # Switch to Qwen
        solver.update_credentials(provider="qwen", api_key="qwen_key", model="qwen-vl-max")
        self.assertEqual(solver.provider, "qwen")
        self.assertEqual(solver.model, "qwen-vl-max")
        self.assertIn("dashscope", solver.base_url)

        # Switch to Gemini
        solver.update_credentials(provider="gemini", api_key="gem_key", model="gemini-3.8-flash")
        self.assertEqual(solver.provider, "gemini")
        self.assertEqual(solver.model, "gemini-3.8-flash")

    def test_image_dimension_capping(self):
        # Verify oversized image downscaling to 1024px
        large_img = Image.new("RGB", (2560, 1440), color=(255, 255, 255))
        solver = QuizSolver(provider="ollama", api_key="")
        # Pre-process should cap dimension at 1024
        max_dim = 1024
        processed = large_img.copy()
        processed.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        self.assertLessEqual(processed.width, 1024)
        self.assertLessEqual(processed.height, 1024)

if __name__ == "__main__":
    unittest.main()
