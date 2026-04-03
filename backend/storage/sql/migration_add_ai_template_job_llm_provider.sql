-- Add LLM provider support to AI template jobs
ALTER TABLE ai_template_jobs
ADD COLUMN IF NOT EXISTS llm_provider VARCHAR(20) NOT NULL DEFAULT 'openai';
