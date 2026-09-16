const FIELDS_URL = '/application-fields.json';
const APPLY_URL = '/apply';
const FORM_ID = 'applicationForm';

function fullOptions(field) {
  const conditionalOptionNames = field.conditional_options ? Object.keys(field.conditional_options) : [];
  return field.options.concat(conditionalOptionNames);
}

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
    for (const option of fullOptions(field)) {
      const opt = document.createElement('option');
      opt.value = option;
      opt.textContent = option;
      select.appendChild(opt);
    }
    wrapper.appendChild(select);
  } else if (field.type === 'multiselect') {
    for (const option of fullOptions(field)) {
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

function getFieldValues(form, name) {
  const values = [];
  for (const el of form.querySelectorAll(`[name="${CSS.escape(name)}"]`)) {
    if (el.type === 'checkbox' || el.type === 'radio') {
      if (el.checked) values.push(el.value);
    } else {
      values.push(el.value);
    }
  }
  return values;
}

function nameConditionalFields(fields, parentName, option) {
  const slug = option.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  const baseName = `${parentName}_${slug}`;
  return fields.map((field, index) => ({
    ...field,
    name: index === 0 ? baseName : `${baseName}_${index + 1}`,
  }));
}

function renderFieldTree(field, form, submitButton) {
  const wrapper = renderField(field);
  form.insertBefore(wrapper, submitButton);

  if (!field.conditional_options) return wrapper;

  const companionWrappersByOption = {};
  for (const [option, companions] of Object.entries(field.conditional_options)) {
    const namedCompanions = nameConditionalFields(companions, field.name, option);
    companionWrappersByOption[option] = namedCompanions.map((companion) => renderFieldTree(companion, form, submitButton));
  }

  function updateCompanionVisibility() {
    const selected = getFieldValues(form, field.name);
    for (const [option, companionWrappers] of Object.entries(companionWrappersByOption)) {
      const isVisible = selected.includes(option);
      for (const companionWrapper of companionWrappers) {
        companionWrapper.hidden = !isVisible;
      }
    }
  }

  form.addEventListener('change', updateCompanionVisibility);
  updateCompanionVisibility();

  return wrapper;
}

function showApplicationResult(form, submitButton, submitButtonText, ok, data) {
  const message = form.querySelector('#applicationFormMessage');
  const succeeded = ok && data && data.success;

  if (message) {
    message.hidden = false;
    if (succeeded) {
      message.textContent = 'Your application has been submitted.';
      message.className = 'form-message is-success';
    } else {
      message.textContent = (data && data.error) || 'Something went wrong. Please try again.';
      message.className = 'form-message is-error';
    }
  }

  if (succeeded) {
    submitButton.textContent = 'Submitted';
    return;
  }
  submitButton.disabled = false;
  submitButton.textContent = submitButtonText;
  if (window.turnstile) {
    window.turnstile.reset();
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById(FORM_ID);
  if (!form) return;
  const submitButton = form.querySelector('button[type="submit"]');
  const submitButtonText = submitButton.textContent;

  fetch(FIELDS_URL)
    .then((response) => response.json())
    .then((fields) => {
      for (const field of fields) {
        renderFieldTree(field, form, submitButton);
      }
    });

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    submitButton.disabled = true;
    submitButton.textContent = 'Submitting…';
    const message = form.querySelector('#applicationFormMessage');
    if (message) message.hidden = true;

    fetch(APPLY_URL, { method: 'POST', body: new FormData(form) })
      .then((response) => {
        return response.json().then((data) => {
          showApplicationResult(form, submitButton, submitButtonText, response.ok, data);
        });
      })
      .catch(() => {
        showApplicationResult(form, submitButton, submitButtonText, false, null);
      });
  });
});
