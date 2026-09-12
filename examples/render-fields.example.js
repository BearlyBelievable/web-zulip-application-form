const FIELDS_URL = '/application-fields.json';
const FORM_ID = 'applicationForm';

function renderField(field) {
  const wrapper = document.createElement('div');

  if (field.type === 'boolean') {
    for (const value of ['true', 'false']) {
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = field.name;
      input.value = value;
      if (field.required) input.required = true;
      wrapper.appendChild(input);
    }
  } else if (field.type === 'select') {
    const select = document.createElement('select');
    select.name = field.name;
    if (field.required) select.required = true;
    for (const option of field.options) {
      const opt = document.createElement('option');
      opt.value = option;
      opt.textContent = option;
      select.appendChild(opt);
    }
    wrapper.appendChild(select);
  } else if (field.type === 'multiselect') {
    for (const option of field.options) {
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.name = field.name;
      input.value = option;
      wrapper.appendChild(input);
    }
  } else if (field.type === 'textarea') {
    const textarea = document.createElement('textarea');
    textarea.name = field.name;
    textarea.maxLength = field.maxlength ?? 1000;
    if (field.minlength !== undefined) textarea.minLength = field.minlength;
    if (field.required) textarea.required = true;
    wrapper.appendChild(textarea);
  } else if (field.type === 'number') {
    const input = document.createElement('input');
    input.type = 'number';
    input.name = field.name;
    if (field.min !== undefined) input.min = field.min;
    if (field.max !== undefined) input.max = field.max;
    if (field.required) input.required = true;
    wrapper.appendChild(input);
  } else {
    const input = document.createElement('input');
    input.type = field.type;
    input.name = field.name;
    input.maxLength = field.maxlength ?? 250;
    if (field.minlength !== undefined) input.minLength = field.minlength;
    if (field.required) input.required = true;
    wrapper.appendChild(input);
  }

  return wrapper;
}

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById(FORM_ID);
  if (!form) return;
  const submitButton = form.querySelector('button[type="submit"]');

  fetch(FIELDS_URL)
    .then((response) => response.json())
    .then((fields) => {
      for (const field of fields) {
        form.insertBefore(renderField(field), submitButton);
      }
    });
});
