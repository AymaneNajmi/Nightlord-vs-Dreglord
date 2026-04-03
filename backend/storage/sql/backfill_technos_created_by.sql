-- Backfill technos.created_by with the chosen admin user_id (replace :admin_id)
UPDATE technos
SET created_by = :admin_id
WHERE created_by IS NULL;

-- Optional: ensure the admin sees all technos via assignment as well
INSERT INTO user_technos (user_id, techno_id)
SELECT :admin_id, t.id
FROM technos t
WHERE NOT EXISTS (
    SELECT 1
    FROM user_technos ut
    WHERE ut.user_id = :admin_id
      AND ut.techno_id = t.id
);
