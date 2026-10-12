document.querySelectorAll("[data-password-toggle]").forEach((toggle) => {
    toggle.addEventListener("click", () => {
        const inputId = toggle.getAttribute("data-password-toggle");
        const input = inputId ? document.getElementById(inputId) : null;

        if (!(input instanceof HTMLInputElement)) {
            return;
        }

        const showPassword = input.type === "password";
        input.type = showPassword ? "text" : "password";
        toggle.setAttribute("aria-pressed", String(showPassword));
        toggle.setAttribute(
            "aria-label",
            showPassword ? "Hide password" : "Show password"
        );
        const icon = toggle.querySelector("i");
        if (icon) {
            icon.classList.toggle("bi-eye", !showPassword);
            icon.classList.toggle("bi-eye-slash", showPassword);
        }
    });
});

document.querySelectorAll("[data-login-form]").forEach((form) => {
    form.addEventListener("submit", () => {
        if (!(form instanceof HTMLFormElement)) {
            return;
        }

        const button = form.querySelector('button[type="submit"]');
        const label = form.querySelector("[data-submit-label]");
        if (!(button instanceof HTMLButtonElement) || !label) {
            return;
        }

        button.disabled = true;
        label.textContent = "Signing in…";
        button.setAttribute("aria-busy", "true");
    });
});