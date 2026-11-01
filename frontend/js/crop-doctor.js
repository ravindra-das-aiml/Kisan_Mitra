const CROP_API_BASE = "http://localhost:8000";

function getCropToken() {
    return localStorage.getItem("access_token");
}

function byId(id) {
    return document.getElementById(id);
}

let selectedImage = null;
let lastCropAnalysis = null;

async function translateCropPayload(data, language = (window.kmLanguage?.() || "en")) {
    if (!data || language === "en") return data;
    const fields = ["crop", "disease", "severity", "warning"];
    const texts = fields.map(k => String(data[k] || ""));
    for (const key of ["symptoms", "treatment", "prevention"]) {
        (Array.isArray(data[key]) ? data[key] : []).forEach(value => texts.push(String(value)));
    }
    const translated = [];
    // Respect the backend translation endpoint limits and keep the UI responsive.
    for (let i = 0; i < texts.length; i += 30) {
        const chunk = texts.slice(i, i + 30);
        try {
            const response = await fetch(CROP_API_BASE + "/api/translate", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ language, texts: chunk })
            });
            if (!response.ok) throw new Error("Translation unavailable");
            const result = await response.json();
            translated.push(...(Array.isArray(result.translations) ? result.translations : chunk));
        } catch (_) { translated.push(...chunk); }
    }
    const out = { ...data }; let index = 0;
    fields.forEach(key => { out[key] = translated[index++] || data[key] || ""; });
    for (const key of ["symptoms", "treatment", "prevention"]) {
        const values = Array.isArray(data[key]) ? data[key] : [];
        out[key] = values.map(value => translated[index++] || value);
    }
    return out;
}

async function renderCropAnalysis(data) {
    const view = await translateCropPayload(data);
    byId("crop").textContent = view.crop || "-";
    byId("disease").textContent = view.disease || "-";
    const confidence = Number(data.confidence);
    byId("confidence").textContent = Number.isFinite(confidence) ? confidence.toFixed(1) + "% AI assessment" : "-";
    byId("severity").textContent = view.severity || "-";
    renderItems("symptoms", view.symptoms); renderItems("treatment", view.treatment); renderItems("prevention", view.prevention);
    byId("warning").textContent = view.warning || "Image-only identification can be uncertain.";
}

document.addEventListener("DOMContentLoaded", () => {

    if (
        !getCropToken() &&
        (
            location.pathname.endsWith("index.html") ||
            location.pathname === "/"
        )
    ) {
        location.href = "login.html";
        return;
    }

    const input = byId("imageInput");
    const chooseBtn = byId("chooseBtn");
    const analyzeBtn = byId("analyzeBtn");

    if (!input) {
        console.error("imageInput was not found");
        return;
    }

    chooseBtn?.addEventListener("click", (event) => {
        event.preventDefault();
        input.click();
    });

    input.addEventListener("change", () => {

        selectedImage = input.files && input.files[0];

        if (!selectedImage) {
            return;
        }

        const error = byId("error");

        const allowedTypes = [
            "image/jpeg",
            "image/png",
            "image/webp"
        ];

        if (!allowedTypes.includes(selectedImage.type)) {
            error.textContent =
                "Please select a JPG, PNG, or WebP image.";

            input.value = "";
            selectedImage = null;

            if (analyzeBtn) {
                analyzeBtn.disabled = true;
            }

            return;
        }

        if (selectedImage.size > 8 * 1024 * 1024) {
            error.textContent =
                "Image must be 8 MB or smaller.";

            input.value = "";
            selectedImage = null;

            if (analyzeBtn) {
                analyzeBtn.disabled = true;
            }

            return;
        }

        error.textContent = "";

        const preview = byId("previewImage");
        const placeholder = byId("uploadPlaceholder");

        const imageUrl = URL.createObjectURL(selectedImage);

        if (preview) {
            preview.src = imageUrl;
            preview.style.display = "block";
        }

        if (placeholder) {
            placeholder.style.display = "none";
        }

        if (analyzeBtn) {
            analyzeBtn.disabled = false;
        }

        console.log("Image selected:", selectedImage.name);
    });

    analyzeBtn?.addEventListener("click", analyzeCrop);
});


async function analyzeCrop() {

    if (!selectedImage) {
        byId("error").textContent =
            "Please choose an image first.";
        return;
    }

    const accessToken = getCropToken();

    if (!accessToken) {
        location.href = "login.html";
        return;
    }

    const form = new FormData();

    form.append("image", selectedImage);

    const btn = byId("analyzeBtn");
    const error = byId("error");
    const status = byId("status");

    btn.disabled = true;
    btn.textContent = "Analyzing with Groq...";
    error.textContent = "";
    status.textContent = "Analyzing";

    try {

        const response = await fetch(
            CROP_API_BASE + "/api/crop/analyze",
            {
                method: "POST",
                headers: {
                    Authorization: "Bearer " + accessToken
                },
                body: form
            }
        );

        let data;

        try {
            data = await response.json();
        } catch {
            throw new Error(
                "Server returned an invalid response."
            );
        }

        if (response.status === 401) {
            localStorage.removeItem("access_token");
            location.href = "login.html";
            return;
        }

        if (!response.ok) {
            throw new Error(
                data.detail || "Crop analysis failed."
            );
        }

        byId("resultEmpty")?.classList.add("hidden");
        byId("result")?.classList.remove("hidden");

        lastCropAnalysis = data;
        await renderCropAnalysis(data);

        if (data.report_id) {
            byId("pdfLink").href =
                CROP_API_BASE +
                "/api/reports/" +
                data.report_id +
                "/pdf?language=" + encodeURIComponent(window.kmLanguage?.() || "en");
        }

        status.textContent = "Complete";

        if (typeof window.loadRecentReports === "function") {
            window.loadRecentReports();
        }

    } catch (e) {

        console.error("Crop analysis error:", e);

        status.textContent = "Error";
        error.textContent =
            e.message || "Something went wrong.";

    } finally {

        btn.disabled = false;
        btn.textContent = "Analyze with Groq";
    }
}


function renderItems(id, items) {

    const element = byId(id);

    if (!element) {
        return;
    }

    element.replaceChildren();

    if (!Array.isArray(items)) {
        return;
    }

    items.forEach((text) => {

        const li = document.createElement("li");

        li.textContent = text;

        element.appendChild(li);
    });
}
document.addEventListener("km-language-changed",()=>{if(lastCropAnalysis) renderCropAnalysis(lastCropAnalysis);const link=byId("pdfLink");if(link&&link.href){const match=link.href.match(/\/api\/reports\/(\d+)\/pdf/);if(match)link.href=`${CROP_API_BASE}/api/reports/${match[1]}/pdf?language=${encodeURIComponent(window.kmLanguage?.()||"en")}`}});
