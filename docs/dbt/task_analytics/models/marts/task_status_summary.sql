select
    statuses.status,
    statuses.status_label,
    statuses.status_order,
    count(tasks.task_id) as task_count
from {{ ref('dim_task_status') }} as statuses
left join {{ ref('fct_tasks') }} as tasks
    on statuses.status = tasks.status
group by
    statuses.status,
    statuses.status_label,
    statuses.status_order
