select
    cast(id as uuid) as task_id,
    trim(title) as title,
    trim(description) as description,
    lower(trim(status)) as status
from {{ ref("raw_tasks") }}
