select
    status,
    status_label,
    status_order,
    is_completed
from {{ ref('task_statuses') }}
