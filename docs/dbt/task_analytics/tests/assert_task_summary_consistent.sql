with expected as (
    select
        statuses.status,
        count(tasks.task_id) as task_count
    from {{ ref('dim_task_status') }} as statuses
    left join {{ ref('fct_tasks') }} as tasks
        on statuses.status = tasks.status
    group by statuses.status
),
totals as (
    select
        (select count(*) from {{ ref('fct_tasks') }}) as fact_count,
        (select sum(task_count) from {{ ref('task_status_summary') }}) as summary_count
)

select coalesce(actual.status, expected.status) as status
from {{ ref('task_status_summary') }} as actual
full outer join expected on actual.status = expected.status
where
    actual.status is null
    or expected.status is null
    or actual.task_count <> expected.task_count
union all
select 'total'
from totals
where fact_count <> summary_count
