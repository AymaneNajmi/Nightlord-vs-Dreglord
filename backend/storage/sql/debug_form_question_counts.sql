-- Usage:
--   - replace :job_id with ai_template_jobs.id
--   - replace :form_id with form_templates.id

-- A) Verify JSON column type on ai_template_jobs.output_payload
SELECT pg_typeof(output_payload)
FROM ai_template_jobs
WHERE id = :job_id;

-- B) Count generated questions per section from output_payload JSON (robust for JSON, cast to JSONB)
SELECT sec->>'sec_id' AS sec_id,
       jsonb_array_length(sec->'questions') AS q_count
FROM ai_template_jobs j
CROSS JOIN LATERAL jsonb_array_elements((j.output_payload->'form'->'sections')::jsonb) sec
WHERE j.id = :job_id
ORDER BY 1;

-- C) Count saved sections for one form
SELECT COUNT(*)
FROM form_sections
WHERE form_id = :form_id;

-- D) Count saved questions per section for one form
SELECT fs.sec_key, COUNT(fq.id) AS q_count
FROM form_sections fs
LEFT JOIN form_questions fq ON fq.section_id = fs.id
WHERE fs.form_id = :form_id
GROUP BY fs.sec_key
ORDER BY fs.sec_key;

-- E) Inspect labels/types order for one form (deep check)
SELECT fs.sec_key, fq.order_index, fq.qtype, fq.label
FROM form_sections fs
JOIN form_questions fq ON fq.section_id = fs.id
WHERE fs.form_id = :form_id
ORDER BY fs.sec_key, fq.order_index;
