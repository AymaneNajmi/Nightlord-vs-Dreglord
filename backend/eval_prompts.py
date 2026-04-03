"""
Prompt Evaluation Script
========================
Applies the evaluation methodology to both Claude and OpenAI 
using LangChain, for every prompt defined in the services/ folder.

For each prompt:
  1. Generate a small evaluation dataset (3 tasks) via Claude
  2. Run each task against Claude and OpenAI sequentially
  3. Grade the output 
  4. Compute the average score per model

Results are written to prompt_eval_results.txt
"""

import json
import re
import ast
import os
import sys
from statistics import mean
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

# Instanciation LangChain des modèles prescrits
llm_claude = ChatAnthropic(model="claude-4-6-sonnet", temperature=0.7)
llm_openai = ChatOpenAI(model="gpt-5-mini", temperature=0.7)
llm_grader = ChatOpenAI(model="gpt-5-mini", temperature=0.0) # Grading via un des LLM

def run_chat_model(llm, system_prompt: str, user_prompt: str, stop=None):
    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=user_prompt))
    
    response = llm.invoke(messages, stop=stop)
    return response.content

# ─── Dataset generation (adapted per-prompt domain) ───────────────────────────

def generate_dataset(prompt_text, prompt_name):
    gen_prompt = f"""
Generate an evaluation dataset for the following prompt/system instruction.
The dataset will be used to evaluate how well an AI performs when given this instruction.

PROMPT TO EVALUATE:
\"\"\"
{prompt_text[:3000]}
\"\"\"

Generate an array of 3 JSON objects. Each object represents a realistic task
that someone would use this prompt for. Each task should test whether the prompt
produces high-quality, well-structured output.

Example output format:
```json
[
    {{
        "task": "Description of a realistic task for this prompt",
        "format": "json" or "python" or "text"
    }}
]
```

Rules:
- Tasks must be relevant
- Generate EXACTLY 3 objects
- Strictly JSON output enclosed in ```json ```
"""
    # Force Claude to generate the dataset
    text = run_chat_model(llm_claude, None, gen_prompt, stop=["```\n\n","``` "])
    # Extract JSON between ticks
    match = re.search(r"```(?:json)?(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    return json.loads(text)

# ─── Grading functions ────────────────────────────────────────────────────────

def grade_by_model(test_case, output):
    eval_prompt = f"""
You are an expert technical reviewer. Your task is to evaluate the following AI-generated solution.

Original Task:
<task>
{test_case["task"]}
</task>

Solution to Evaluate:
<solution>
{output}
</solution>

Output Format
Provide your evaluation as a structured JSON object with the following fields:
- "strengths": An array of 1-3 key strengths
- "weaknesses": An array of 1-3 key areas for improvement
- "reasoning": A concise explanation of your overall assessment
- "score": A number between 1-10

Respond with strictly JSON exactly formatted as requested. No extra text.
"""
    eval_text = run_chat_model(llm_grader, None, eval_prompt)
    match = re.search(r"```(?:json)?(.*?)```", eval_text, re.DOTALL)
    if match:
        eval_text = match.group(1).strip()
    return json.loads(eval_text)

def validate_json(text):
    try:
        match = re.search(r"```(?:json)?(.*?)```", text, re.DOTALL)
        if match: text = match.group(1).strip()
        json.loads(text)
        return 10
    except json.JSONDecodeError:
        return 0

def validate_python(text):
    try:
        match = re.search(r"```(?:python)?(.*?)```", text, re.DOTALL)
        if match: text = match.group(1).strip()
        ast.parse(text)
        return 10
    except SyntaxError:
        return 0

def validate_text(text):
    stripped = text.strip()
    if len(stripped) > 50: return 10
    elif len(stripped) > 10: return 5
    return 0

def grade_syntax(response, test_case):
    fmt = test_case.get("format", "text")
    if fmt == "json":
        return validate_json(response)
    elif fmt == "python":
        return validate_python(response)
    else:
        return validate_text(response)

# ─── Test execution ──────────────────────────────────────────────────────────

def run_test_case_for_model(llm, test_case, system_prompt):
    user_prompt = f"Please solve the following task:\n\n{test_case['task']}\n\n* Respond with well-structured content."
    output = run_chat_model(llm, system_prompt, user_prompt)
    
    try:
        model_grade = grade_by_model(test_case, output)
        model_score = float(model_grade.get("score", 0))
        reasoning = model_grade.get("reasoning", "No reasoning provided.")
    except Exception as e:
        model_score = 0
        reasoning = f"Grading failed: {str(e)}"

    syntax_score = grade_syntax(output, test_case)
    score = (model_score + syntax_score) / 2
    return score, reasoning

def run_eval(dataset, system_prompt):
    results_claude = []
    results_openai = []
    
    for test_case in dataset:
        # Evaluate Claude
        c_score, c_reason = run_test_case_for_model(llm_claude, test_case, system_prompt)
        results_claude.append({"score": c_score, "reasoning": c_reason})
        
        # Evaluate OpenAI
        o_score, o_reason = run_test_case_for_model(llm_openai, test_case, system_prompt)
        results_openai.append({"score": o_score, "reasoning": o_reason})

    avg_claude = mean([r["score"] for r in results_claude]) if results_claude else 0
    avg_openai = mean([r["score"] for r in results_openai]) if results_openai else 0
    
    return avg_claude, avg_openai

# ─── All prompts from services/ ──────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.openai_writer import (
    SYSTEM_PROMPT as OW_SYSTEM_PROMPT,
    RICHNESS_BLOCK as OW_RICHNESS_BLOCK,
    INTENT_RULES as OW_INTENT_RULES,
    CONTRAINTE_STRUCTURE as OW_CONTRAINTE_STRUCTURE,
)
from app.services.ai_form_builder_rich import SYSTEM_PROMPT as AFBR_SYSTEM_PROMPT
from app.services.hardware_generator import SYSTEM_PROMPT as HG_SYSTEM_PROMPT
from app.services.ai_template_builder import (
    SYSTEM_PROMPT_OUTLINE as ATB_SYSTEM_PROMPT_OUTLINE,
    SYSTEM_PROMPT_QUESTIONS as ATB_SYSTEM_PROMPT_QUESTIONS,
)

LLM_ANALYZER_SECTION_PROMPT = "Générer des questions spécifiques..."
LLM_ANALYZER_SYSTEM = "Tu es un expert réseau et sécurité."

ALL_PROMPTS = {
    "openai_writer_SYSTEM": OW_SYSTEM_PROMPT,
    "ai_form_builder_rich_SYSTEM": AFBR_SYSTEM_PROMPT,
    "hardware_generator_SYSTEM": HG_SYSTEM_PROMPT,
    "ai_template_builder_OUTLINE": ATB_SYSTEM_PROMPT_OUTLINE,
    "ai_template_builder_QUESTIONS": ATB_SYSTEM_PROMPT_QUESTIONS,
}

def main():
    output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_eval_results.txt")
    results_lines = []

    total = len(ALL_PROMPTS)
    for idx, (prompt_name, prompt_text) in enumerate(ALL_PROMPTS.items(), start=1):
        print(f"\n[{idx}/{total}] Evaluating: {prompt_name}")
        try:
            dataset = generate_dataset(prompt_text, prompt_name)
            avg_claude, avg_openai = run_eval(dataset, prompt_text)
            line = f'Average score for ("{prompt_name}") : Claude: {avg_claude:.2f} | OpenAI: {avg_openai:.2f}'
            print(f"  → Result: {line}")
            results_lines.append(line)
        except Exception as e:
            err = f'Average score for ("{prompt_name}") : ERROR - {str(e)[:100]}'
            print(f"  ✗ {err}")
            results_lines.append(err)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(results_lines) + "\n")
    print(f"\nResults written to: {output_file}")

if __name__ == "__main__":
    main()
