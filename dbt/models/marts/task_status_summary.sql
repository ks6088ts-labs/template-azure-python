select
    status,
    count(*) as task_count
from {{ ref("stg_tasks") }}
group by status
