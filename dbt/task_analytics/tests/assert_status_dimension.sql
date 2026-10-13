with expected as (
    select 'todo' as status, 1 as status_order, false as is_completed
    union all
    select 'in_progress', 2, false
    union all
    select 'done', 3, true
)

select coalesce(actual.status, expected.status) as status
from {{ ref('dim_task_status') }} as actual
full outer join expected on actual.status = expected.status
where
    actual.status is null
    or expected.status is null
    or actual.status_order <> expected.status_order
    or actual.is_completed <> expected.is_completed
