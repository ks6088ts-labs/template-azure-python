select
    tasks.task_id,
    tasks.task_title,
    tasks.task_description,
    tasks.status,
    statuses.is_completed
from {{ ref('stg_tasks') }} as tasks
left join {{ ref('dim_task_status') }} as statuses
    on tasks.status = statuses.status
