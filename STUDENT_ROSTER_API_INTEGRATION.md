# Student Roster API

These endpoints are for approved school-system integrations. They use the same Bearer API key as the results API.

```text
Authorization: Bearer <API_KEY>
```

## Endpoints

- `GET /api/v1/students?page=1&per_page=100` lists students with pagination.
- `POST /api/v1/students` creates one student.
- `PUT` or `PATCH /api/v1/students/<student_number>` updates one student.
- `POST /api/v1/students/bulk` creates or updates an array using `student_number` as the upsert key.
- `GET /api/v1/students/lookup?student_number=...` returns the compact lookup response used by existing integrations.

The minimum create fields are `student_number`, `first_name`, and `last_name`. The create and bulk endpoints also accept a single `name` field for systems that do not split names. Optional fields include `middle_name`, `class_name`, `study_area`, `reference_number`, and ISO `date_of_birth`.

There is intentionally no delete endpoint. A school integration must not silently delete academic records. Deletions or withdrawals should be handled as an explicit review workflow.
