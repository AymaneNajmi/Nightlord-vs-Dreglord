CREATE TABLE IF NOT EXISTS form_module_answers (
  id INTEGER PRIMARY KEY,
  form_id INTEGER NOT NULL REFERENCES form_templates(id) ON DELETE CASCADE,
  question_id INTEGER NOT NULL REFERENCES form_questions(id) ON DELETE CASCADE,
  reference VARCHAR(255) NOT NULL,
  output_json TEXT,
  output_summary_text TEXT,
  output_summary_html TEXT,
  output_bom_json TEXT,
  output_docx_path VARCHAR(500),
  generated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_form_module_answers_form_question UNIQUE (form_id, question_id)
);

ALTER TABLE form_module_answers ADD COLUMN IF NOT EXISTS output_summary_text TEXT;
ALTER TABLE form_module_answers ADD COLUMN IF NOT EXISTS output_summary_html TEXT;
ALTER TABLE form_module_answers ADD COLUMN IF NOT EXISTS output_bom_json TEXT;

CREATE INDEX IF NOT EXISTS ix_form_module_answers_form_id ON form_module_answers(form_id);
CREATE INDEX IF NOT EXISTS ix_form_module_answers_question_id ON form_module_answers(question_id);
