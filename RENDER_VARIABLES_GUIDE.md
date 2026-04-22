# How to Edit Variables Using Flask render_template()

This guide explains how to pass variables from your Flask application (Python) to your HTML templates and how to modify/edit them within templates.

## Table of Contents
1. [Basic Variable Passing](#basic-variable-passing)
2. [Editing Variables in Templates](#editing-variables-in-templates)
3. [Working with Data Types](#working-with-data-types)
4. [Advanced Examples](#advanced-examples)
5. [Common Patterns](#common-patterns)

---

## 1. Basic Variable Passing

### Passing Variables from Flask to Template

In `app.py`, pass variables using the `render_template()` function:

```python
@app.route('/dashboard')
@login_required
def dashboard():
    # Define variables
    student_name = "John Doe"
    total_score = 85.5
    student_list = ["Alice", "Bob", "Charlie"]
    student_dict = {"name": "Jane", "age": 15, "class": "Form 3"}
    
    # Pass variables to template
    return render_template('dashboard.html',
                          student_name=student_name,
                          total_score=total_score,
                          students=student_list,
                          student_info=student_dict)
```

### Accessing Variables in Template

In `templates/dashboard.html`, access these variables using Jinja2 syntax:

```html
<h1>Welcome, {{ student_name }}</h1>
<p>Your score: {{ total_score }}</p>

<!-- For lists -->
<ul>
    {% for student in students %}
    <li>{{ student }}</li>
    {% endfor %}
</ul>

<!-- For dictionaries -->
<p>Name: {{ student_info.name }}</p>
<p>Class: {{ student_info['class'] }}</p>
```

---

## 2. Editing Variables in Templates

### Using Filters (Read-Only)

Jinja2 filters allow you to format variables without modifying the original:

```html
<!-- Uppercase -->
<p>{{ student_name|upper }}</p>

<!-- Lowercase -->
<p>{{ student_name|lower }}</p>

<!-- Title case -->
<p>{{ student_name|title }}</p>

<!-- Date formatting -->
<p>{{ created_date|strftime('%B %d, %Y') }}</p>

<!-- Number formatting -->
<p>Score: {{ total_score|round(1) }}%</p>

<!-- Default value if empty -->
<p>Class: {{ class_name|default('Unassigned') }}</p>

<!-- Replace text -->
<p>{{ subject|replace('_', ' ')|title }}</p>
```

### Using Jinja2 Set Statement (Temporary Variables)

Create temporary variables in templates:

```html
<!-- Create a new variable in the template -->
{% set full_title = student_name|upper %}
<h2>{{ full_title }}</h2>

<!-- Combine multiple variables -->
{% set greeting = "Welcome, " ~ student_name ~ "!" %}
<p>{{ greeting }}</p>

<!-- Math operations -->
{% set percentage = (current_score / max_score) * 100 %}
<p>Score: {{ percentage|round(1) }}%</p>

<!-- String concatenation -->
{% set class_info = class_name ~ " - " ~ subject %}
<p>{{ class_info }}</p>
```

### Using Conditional Assignment

```html
<!-- Set variable based on condition -->
{% if total_score >= 80 %}
    {% set grade = "A" %}
{% elif total_score >= 70 %}
    {% set grade = "B" %}
{% else %}
    {% set grade = "C" %}
{% endif %}
<p>Grade: {{ grade }}</p>

<!-- Set variable based on user role -->
{% set can_edit = current_user.is_admin() or current_user.is_teacher() %}
{% if can_edit %}
    <a href="{{ url_for('edit_assessment', assessment_id=assessment.id) }}">Edit</a>
{% endif %}
```

---

## 3. Working with Data Types

### Strings

```python
# Python
user_name = "john_doe"
return render_template('template.html', name=user_name)
```

```html
<!-- Jinja2 Template -->
<!-- Basic access -->
<p>{{ name }}</p>

<!-- String methods -->
<p>{{ name|capitalize }}</p>
<p>{{ name|replace('_', ' ')|title }}</p>
<p>{{ name|length }} characters</p>

<!-- Concatenation -->
{% set full_intro = "User: " ~ name %}
<p>{{ full_intro }}</p>
```

### Numbers

```python
# Python
score = 85
max_score = 100
return render_template('template.html', score=score, max_score=max_score)
```

```html
<!-- Jinja2 Template -->
<!-- Math operations -->
{% set percentage = (score / max_score) * 100 %}
<p>{{ percentage|round(1) }}%</p>

<!-- Conditionals based on numbers -->
{% if score >= 80 %}
    <span style="color: green;">Excellent!</span>
{% elif score >= 60 %}
    <span style="color: orange;">Good</span>
{% else %}
    <span style="color: red;">Needs Improvement</span>
{% endif %}
```

### Lists and Loops

```python
# Python
students = ["Alice", "Bob", "Charlie"]
assessments = [
    {"name": "Alice", "score": 85},
    {"name": "Bob", "score": 92},
    {"name": "Charlie", "score": 78}
]
return render_template('template.html', students=students, assessments=assessments)
```

```html
<!-- Jinja2 Template -->
<!-- Simple list -->
<ul>
    {% for student in students %}
        <li>{{ student }}</li>
    {% endfor %}
</ul>

<!-- List with index -->
<ol>
    {% for student in students %}
        <li>#{{ loop.index }} - {{ student }}</li>
    {% endfor %}
</ol>

<!-- List of dictionaries -->
<table>
    {% for assessment in assessments %}
        <tr>
            <td>{{ assessment.name }}</td>
            <td>{{ assessment.score }}</td>
        </tr>
    {% endfor %}
</table>

<!-- Create new list in template -->
{% set top_students = assessments|selectattr('score', 'greaterthan', 80)|list %}
<p>Top performers: {{ top_students|length }}</p>
```

### Dictionaries

```python
# Python
student_info = {
    "name": "John Doe",
    "age": 15,
    "class": "Form 3",
    "subjects": ["Math", "English", "Science"]
}
return render_template('template.html', student=student_info)
```

```html
<!-- Jinja2 Template -->
<!-- Access by key -->
<p>Name: {{ student.name }}</p>
<p>Age: {{ student['age'] }}</p>

<!-- Loop through dict items -->
{% for key, value in student.items() %}
    <p>{{ key }}: {{ value }}</p>
{% endfor %}

<!-- Create modified dictionary in template -->
{% set student_display = {
    'full_name': student.name|upper,
    'display_class': 'Form ' ~ student.class,
    'subject_count': student.subjects|length
} %}
<p>{{ student_display.full_name }} ({{ student_display.display_count }} subjects)</p>
```

---

## 4. Advanced Examples

### Example 1: Student Assessment Form

```python
# app.py
@app.route('/assessments/new', methods=['GET', 'POST'])
def new_assessment():
    form = AssessmentForm()
    
    # Get students from database
    if current_user.is_teacher():
        students = Student.query.filter_by(
            class_name=current_user.class_name
        ).order_by(Student.last_name).all()
    else:
        students = Student.query.all()
    
    # Create grouped dictionary for template
    grouped_students = {}
    for student in students:
        class_name = student.get_class_display() or 'Unassigned'
        if class_name not in grouped_students:
            grouped_students[class_name] = []
        grouped_students[class_name].append(student)
    
    return render_template('assessment_form.html',
                          form=form,
                          grouped_students=grouped_students,
                          teacher_name=current_user.username)
```

```html
<!-- templates/assessment_form.html -->
<div class="form-group">
    <label>Student Name</label>
    <select name="student_name" class="form-select">
        {% for class_name, students_list in grouped_students.items() %}
            <optgroup label="Form: {{ class_name }}">
                {% for student in students_list %}
                    <option value="{{ student.student_number }}">
                        {{ student.full_name() }} ({{ student.student_number }})
                    </option>
                {% endfor %}
            </optgroup>
        {% endfor %}
    </select>
</div>

<!-- Create formatted display string in template -->
{% set form_header = "Create Assessment - " ~ teacher_name %}
<h2>{{ form_header }}</h2>
```

### Example 2: Dashboard with Calculations

```python
# app.py
@app.route('/dashboard')
def dashboard():
    current_student = Student.query.get(student_id)
    assessments = current_student.assessments
    
    # Calculate statistics (could also be done in template)
    total_assessments = len(assessments)
    
    return render_template('dashboard.html',
                          student=current_student,
                          assessments=assessments,
                          total_count=total_assessments)
```

```html
<!-- templates/dashboard.html -->
<!-- Calculations in template -->
{% set scores = [] %}
{% for assessment in assessments %}
    {% set _ = scores.append(assessment.score) %}
{% endfor %}

{% set avg_score = (scores|sum / scores|length)|round(1) if scores|length > 0 else 0 %}
<p>Average Score: {{ avg_score }}</p>

<!-- Create formatted report -->
{% set report_data = {
    'student': student.full_name(),
    'class': student.get_class_display(),
    'assessments': assessments|length,
    'average': avg_score,
    'status': 'Active' if avg_score >= 60 else 'At Risk'
} %}

<div class="report">
    <h3>{{ report_data.student }} - {{ report_data.class }}</h3>
    <p>Total Assessments: {{ report_data.assessments }}</p>
    <p>Average: {{ report_data.average }}%</p>
    <p style="color: {% if report_data.status == 'Active' %}green{% else %}red{% endif %}">
        {{ report_data.status }}
    </p>
</div>
```

---

## 5. Common Patterns

### Pattern 1: Conditional Rendering with Editable Fields

```html
<!-- Show read-only value if admin, editable field if not -->
{% if current_user.is_admin() %}
    <input type="text" value="{{ student.class_name }}" readonly>
{% else %}
    <input type="text" name="class_name" value="{{ student.class_name }}">
{% endif %}
```

### Pattern 2: Formatted Display with Set

```html
<!-- Create display-friendly versions of database values -->
{% set status_display = {
    'active': '<span class="badge badge-success">Active</span>',
    'inactive': '<span class="badge badge-danger">Inactive</span>',
    'pending': '<span class="badge badge-warning">Pending</span>'
} %}

<p>Status: {{ status_display.get(student.status, 'Unknown')|safe }}</p>
```

### Pattern 3: Filtering Data in Template

```html
<!-- Filter list in template -->
{% set high_scorers = assessments|selectattr('score', 'greaterthan', 80)|list %}
<p>Students scoring above 80: {{ high_scorers|length }}</p>

{% for assessment in high_scorers %}
    <p>{{ assessment.student.full_name() }}: {{ assessment.score }}</p>
{% endfor %}
```

### Pattern 4: Building URLs with Variables

```html
<!-- Create dynamic URLs -->
{% set edit_url = url_for('edit_assessment', assessment_id=assessment.id) %}
<a href="{{ edit_url }}">Edit Assessment</a>

<!-- With parameters -->
{% set student_url = url_for('student_view', student_id=student.id) ~ '?subject=' ~ current_subject %}
<a href="{{ student_url }}">View Student</a>
```

### Pattern 5: Working with Current User

```html
<!-- Check user permissions and set variables accordingly -->
{% set can_edit = current_user.is_admin() or current_user.is_teacher() %}
{% set can_delete = current_user.is_admin() %}

{% set user_role_display = {
    'admin': 'Administrator',
    'teacher': 'Teacher',
    'student': 'Student',
    'parent': 'Parent'
} %}

<p>Role: {{ user_role_display.get(current_user.role, current_user.role) }}</p>

{% if can_edit %}
    <button class="btn btn-edit">Edit</button>
{% endif %}

{% if can_delete %}
    <button class="btn btn-danger">Delete</button>
{% endif %}
```

---

## Summary of Key Concepts

| Concept | Syntax | Purpose |
|---------|--------|---------|
| **Access variable** | `{{ variable_name }}` | Display value |
| **Access dict/object** | `{{ obj.key }}` or `{{ obj['key'] }}` | Access nested value |
| **Use filter** | `{{ variable\|filter_name }}` | Format/modify display |
| **Chain filters** | `{{ variable\|filter1\|filter2 }}` | Apply multiple filters |
| **Set variable** | `{% set var = value %}` | Create temp variable |
| **Conditional** | `{% if condition %}...{% endif %}` | Conditional display |
| **Loop** | `{% for item in list %}...{% endfor %}` | Iterate over data |
| **String concat** | `{{ "text " ~ variable }}` | Combine strings |
| **Math in template** | `{{ (a / b) * 100 }}` | Perform calculations |

---

## Notes

- **Filters are read-only**: They don't modify the original variable passed from Python
- **Set creates temporary variables**: Only exist within the template
- **Use Jinja2 for display logic**: Keep business logic in Python
- **Escape HTML**: Use `|safe` filter carefully (security risk!)
- **Performance**: Complex calculations in template = slower rendering

For more information, visit the [Jinja2 Documentation](https://jinja.palletsprojects.com/).
