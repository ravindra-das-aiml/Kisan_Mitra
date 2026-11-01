const AUTH_API_BASE = "http://localhost:8000";

function saveToken(token) {
    localStorage.setItem("access_token", token);
}

function getAuthToken() {
    return localStorage.getItem("access_token");
}

async function sendAuthRequest(url, payload) {
    const response = await fetch(AUTH_API_BASE + url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    });

    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.detail || "Request failed");
    }

    return data;
}

document.addEventListener("DOMContentLoaded", () => {

    const loginForm = document.getElementById("loginForm");
    const registerForm = document.getElementById("registerForm");

    const emailInput = document.getElementById("email");
    const passwordInput = document.getElementById("password");
    const fullNameInput = document.getElementById("fullName");
    const roleInput = document.getElementById("role");

    const authError = document.getElementById("authError");

    // LOGIN
    if (loginForm) {
        loginForm.addEventListener("submit", async (event) => {
            event.preventDefault();

            try {
                if (authError) {
                    authError.textContent = "";
                }

                const data = await sendAuthRequest(
                    "/api/auth/login",
                    {
                        email: emailInput.value.trim(),
                        password: passwordInput.value
                    }
                );

                // Save JWT
                saveToken(data.access_token);

                // IMPORTANT:
                // Backend returns:
                // data.user.role = "user" or "admin"

                if (data.user?.role === "admin") window.location.href = "admin.html";
                else if (data.user?.role === "buyer") window.location.href = "marketplace.html";
                else window.location.href = "index.html";

            } catch (error) {
                console.error("Login error:", error);

                if (authError) {
                    authError.textContent = error.message;
                }
            }
        });
    }

    // REGISTER
    if (registerForm) {
        registerForm.addEventListener("submit", async (event) => {
            event.preventDefault();

            try {
                if (authError) {
                    authError.textContent = "";
                }

                const data = await sendAuthRequest(
                    "/api/auth/register",
                    {
                        full_name: fullNameInput.value.trim(),
                        email: emailInput.value.trim(),
                        password: passwordInput.value,
                        role: roleInput ? roleInput.value : "farmer"
                    }
                );

                saveToken(data.access_token);

                /*
                 * Normal registration creates a "user".
                 * Your backend can create an admin automatically
                 * when ADMIN_EMAIL matches the registered email.
                 */

                if (data.user?.role === "admin") window.location.href = "admin.html";
                else if (data.user?.role === "buyer") window.location.href = "marketplace.html";
                else window.location.href = "index.html";

            } catch (error) {
                console.error("Registration error:", error);

                if (authError) {
                    authError.textContent = error.message;
                }
            }
        });
    }
});