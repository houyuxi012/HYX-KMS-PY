(function () {
    'use strict';
    document.addEventListener('DOMContentLoaded', function () {
        const languageSelect = document.getElementById('language-select');
        if (languageSelect) {
            languageSelect.addEventListener('change', function () {
                languageSelect.form.requestSubmit();
            });
            const submit = languageSelect.form.querySelector('button');
            if (submit) submit.hidden = true;
        }
        const burger = document.querySelector('.navbar-burger');
        const menu = document.getElementById('kms-nav-menu');
        if (burger && menu) {
            burger.addEventListener('click', function () {
                burger.classList.toggle('is-active');
                menu.classList.toggle('is-active');
                burger.setAttribute('aria-expanded', String(menu.classList.contains('is-active')));
            });
        }
        for (const element of document.getElementsByClassName('convert_timestamp')) {
            const timestamp = new Date(element.textContent);
            if (!Number.isNaN(timestamp.getTime())) {
                element.textContent = timestamp.toLocaleString(document.documentElement.lang);
            }
        }
    });
}());
