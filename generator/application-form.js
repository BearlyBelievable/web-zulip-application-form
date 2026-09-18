(function () {
    const applicationForm = document.getElementById('applicationForm');
    const applicationSubmitButton = applicationForm.querySelector('button[type="submit"]');
    const applicationMessage = document.getElementById('applicationFormMessage');
    const applicationSubmitButtonText = applicationSubmitButton.textContent;

    function fieldValue(name) {
        const checked = applicationForm.querySelectorAll(`[name="${name}"]:checked`);
        if (checked.length) {
            if (checked[0].type === 'checkbox') {
                return Array.from(checked).map((el) => el.value);
            }
            return checked[0].value;
        }
        const select = applicationForm.querySelector(`select[name="${name}"]`);
        return select ? select.value : '';
    }

    function syncCompanion(companion) {
        const fieldName = companion.getAttribute('data-companion-of');
        const expected = companion.getAttribute('data-companion-when');
        const value = fieldValue(fieldName);
        const show = Array.isArray(value) ? value.includes(expected) : value === expected;
        companion.hidden = !show;
        companion.querySelectorAll('input, textarea, select').forEach((input) => {
            if (input.dataset.required === 'true') {
                input.required = show;
            }
        });
    }

    applicationForm.querySelectorAll('[data-companion-of]').forEach((companion) => {
        const fieldName = companion.getAttribute('data-companion-of');
        applicationForm.querySelectorAll(`[name="${fieldName}"]`).forEach((input) => {
            input.addEventListener('change', () => syncCompanion(companion));
        });
        syncCompanion(companion);
    });

    applicationForm.querySelectorAll('[data-multiselect-required]').forEach((group) => {
        const boxes = group.querySelectorAll('input[type="checkbox"]');
        function syncMultiselectValidity() {
            const anyChecked = Array.from(boxes).some((box) => box.checked);
            boxes.forEach((box, index) => {
                box.setCustomValidity(!anyChecked && index === 0 ? 'Please select at least one option.' : '');
            });
        }
        boxes.forEach((box) => box.addEventListener('change', syncMultiselectValidity));
        syncMultiselectValidity();
    });

    function updateCounter(input) {
        const field = input.closest('.form-field');
        const counter = field && field.querySelector('.char-counter');
        if (!counter) return;
        const max = input.maxLength;
        const used = input.value.length;
        const nearLimit = used >= max * 0.9 && used < max;
        const atLimit = used >= max;
        counter.textContent = nearLimit || atLimit ? `${used} / ${max}` : '';
        counter.classList.toggle('is-near-limit', nearLimit);
        counter.classList.toggle('is-at-limit', atLimit);
    }

    applicationForm.querySelectorAll('input[maxlength], textarea[maxlength]').forEach(updateCounter);
    applicationForm.addEventListener('input', (event) => {
        if (event.target.maxLength >= 0) updateCounter(event.target);
    });

    const touchedFields = new WeakSet();

    function showFieldValidity(field) {
        const invalidInputs = field.querySelectorAll('input:invalid, select:invalid, textarea:invalid');
        const ownInvalidInput = Array.from(invalidInputs).some((input) => {
            const companion = input.closest('.form-field-companion');
            return !companion || !field.contains(companion);
        });
        field.classList.toggle('has-error', ownInvalidInput);
    }

    function updateSubmitAvailability() {
        applicationSubmitButton.disabled = !applicationForm.checkValidity();
    }

    applicationForm.addEventListener('focusout', (event) => {
        const field = event.target.closest('.form-field');
        if (field) {
            touchedFields.add(field);
            showFieldValidity(field);
        }
        updateSubmitAvailability();
    });
    applicationForm.addEventListener('change', (event) => {
        const field = event.target.closest('.form-field');
        if (field) {
            touchedFields.add(field);
            showFieldValidity(field);
        }
        updateSubmitAvailability();
    });
    applicationForm.addEventListener('input', (event) => {
        const field = event.target.closest('.form-field');
        if (field && touchedFields.has(field)) showFieldValidity(field);
        updateSubmitAvailability();
    });
    updateSubmitAvailability();

    function showApplicationResult(ok, data) {
        applicationMessage.hidden = false;
        if (ok && data && data.success) {
            applicationMessage.textContent = 'Your application has been submitted.';
            applicationMessage.className = 'form-message is-success';
            applicationSubmitButton.textContent = 'Submitted';
            return;
        }
        applicationMessage.textContent = (data && data.error) || 'Something went wrong. Please try again.';
        applicationMessage.className = 'form-message is-error';
        applicationSubmitButton.disabled = false;
        applicationSubmitButton.textContent = applicationSubmitButtonText;
        if (window.turnstile) {
            window.turnstile.reset();
        }
    }

    applicationForm.addEventListener('submit', (event) => {
        event.preventDefault();

        if (!applicationForm.checkValidity()) {
            applicationForm.reportValidity();
            return;
        }

        applicationSubmitButton.disabled = true;
        applicationSubmitButton.textContent = 'Submitting…';
        applicationMessage.hidden = true;

        fetch('/apply', { method: 'POST', body: new FormData(applicationForm) })
            .then((response) => {
                return response.json().then((data) => {
                    showApplicationResult(response.ok, data);
                });
            })
            .catch(() => {
                showApplicationResult(false, null);
            });
    });
})();
