select task_id
from {{ ref('stg_tasks') }}
where
    not regexp_full_match(
        task_id,
        '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
    )
    or length(task_title) = 0
    or length(task_title) > 200
    or length(task_description) > 2000
