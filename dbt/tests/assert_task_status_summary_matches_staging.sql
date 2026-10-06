with staging_total as (
    select count(*) as task_count
    from {{ ref("stg_tasks") }}
),

summary_total as (
    select coalesce(sum(task_count), 0) as task_count
    from {{ ref("task_status_summary") }}
)

select
    staging_total.task_count as staging_task_count,
    summary_total.task_count as summary_task_count
from staging_total
cross join summary_total
where staging_total.task_count != summary_total.task_count
