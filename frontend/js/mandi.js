const API_BASE = "http://localhost:8000";

const stateFilter = document.getElementById("stateFilter");
const districtFilter = document.getElementById("districtFilter");
const commodityFilter = document.getElementById("commodityFilter");
const loadMandi = document.getElementById("loadMandi");

const mandiStatus = document.getElementById("mandiStatus");
const mandiRows = document.getElementById("mandiRows");
const mandiNote = document.getElementById("mandiNote");
const mandiError = document.getElementById("mandiError");


// State -> District data
const stateDistricts = {
    "Punjab": [
        "Amritsar",
        "Barnala",
        "Bathinda",
        "Faridkot",
        "Fatehgarh Sahib",
        "Fazilka",
        "Ferozepur",
        "Gurdaspur",
        "Hoshiarpur",
        "Jalandhar",
        "Kapurthala",
        "Ludhiana",
        "Malerkotla",
        "Mansa",
        "Moga",
        "Pathankot",
        "Patiala",
        "Rupnagar",
        "Sahibzada Ajit Singh Nagar",
        "Sangrur",
        "Shahid Bhagat Singh Nagar",
        "Sri Muktsar Sahib",
        "Tarn Taran"
    ],

    "Haryana": [
        "Ambala",
        "Bhiwani",
        "Charkhi Dadri",
        "Faridabad",
        "Fatehabad",
        "Gurugram",
        "Hisar",
        "Jhajjar",
        "Jind",
        "Kaithal",
        "Karnal",
        "Kurukshetra",
        "Mahendragarh",
        "Nuh",
        "Palwal",
        "Panchkula",
        "Panipat",
        "Rewari",
        "Rohtak",
        "Sirsa",
        "Sonipat",
        "Yamunanagar"
    ],

    "Himachal Pradesh": [
        "Bilaspur",
        "Chamba",
        "Hamirpur",
        "Kangra",
        "Kinnaur",
        "Kullu",
        "Lahaul and Spiti",
        "Mandi",
        "Shimla",
        "Sirmaur",
        "Solan",
        "Una"
    ],

    "Uttar Pradesh": [
        "Agra",
        "Aligarh",
        "Allahabad",
        "Azamgarh",
        "Bareilly",
        "Ghaziabad",
        "Gorakhpur",
        "Kanpur",
        "Lucknow",
        "Mathura",
        "Meerut",
        "Moradabad",
        "Muzaffarnagar",
        "Varanasi"
    ],

    "Rajasthan": [
        "Ajmer",
        "Alwar",
        "Bikaner",
        "Jaipur",
        "Jaisalmer",
        "Jodhpur",
        "Kota",
        "Sikar",
        "Sri Ganganagar",
        "Udaipur"
    ],

    "Maharashtra": [
        "Ahmednagar",
        "Akola",
        "Amravati",
        "Aurangabad",
        "Dhule",
        "Jalgaon",
        "Kolhapur",
        "Latur",
        "Nagpur",
        "Nashik",
        "Pune",
        "Sangli",
        "Satara",
        "Solapur"
    ]
};


// Use the full dataset lists when js/mandi-data.js has been generated
// (node tools/build-mandi-data.mjs); otherwise fall back to the built-in lists.
const MANDI_LISTS = (() => {
    if (window.MANDI_DATA && window.MANDI_DATA.states) {
        return { districts: window.MANDI_DATA.states, commodities: window.MANDI_DATA.commodities || [] };
    }
    const fb = window.MANDI_FALLBACK || { states: [], commodities: [] };
    const districts = { ...stateDistricts };
    fb.states.forEach(st => { if (!districts[st]) districts[st] = []; });
    return { districts, commodities: fb.commodities };
})();
Object.keys(stateDistricts).forEach(k => delete stateDistricts[k]);
Object.assign(stateDistricts, MANDI_LISTS.districts);

// Free-text district box for states whose district list is not loaded
const districtText = document.createElement("input");
districtText.id = "districtText";
districtText.placeholder = "Type district name";
districtText.setAttribute("aria-label", "District name");
districtText.hidden = true;
districtFilter.insertAdjacentElement("afterend", districtText);

function loadCommodities() {
    if (!MANDI_LISTS.commodities.length) return;
    commodityFilter.innerHTML = '<option value="">Select Commodity</option>';
    MANDI_LISTS.commodities.forEach(c => {
        const o = document.createElement("option");
        o.value = c; o.textContent = c;
        commodityFilter.appendChild(o);
    });
}

// Populate state dropdown
function loadStates() {
    loadCommodities();
    // Completely reset the state dropdown
    stateFilter.innerHTML = "";

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Select State";
    placeholder.selected = true;
    placeholder.disabled = true;

    stateFilter.appendChild(placeholder);

    Object.keys(stateDistricts)
        .sort()
        .forEach(state => {
            const option = document.createElement("option");

            option.value = state;
            option.textContent = state;

            stateFilter.appendChild(option);
        });
}


// When state changes, update districts
stateFilter.addEventListener("change", () => {

    const selectedState = stateFilter.value;

    districtFilter.innerHTML =
        `<option value="">Select District</option>`;

    districtFilter.disabled = true;
    districtFilter.hidden = false;
    districtText.hidden = true;
    districtText.value = "";

    if (!selectedState) {
        return;
    }

    const districts = stateDistricts[selectedState] || [];
    if (!districts.length) {
        districtFilter.hidden = true;
        districtText.hidden = false;
    }

    districts.forEach(district => {

        const option = document.createElement("option");

        option.value = district;
        option.textContent = district;

        districtFilter.appendChild(option);
    });

    districtFilter.disabled = false;

    mandiStatus.textContent =
        `Select a district in ${selectedState}.`;
});


// Load mandi prices
loadMandi.addEventListener("click", async () => {

    const state = stateFilter.value;
    const district = districtFilter.value || districtText.value.trim();
    const commodity = commodityFilter.value;

    mandiError.textContent = "";
    mandiNote.textContent = "";

    if (!state) {
        mandiError.textContent = "Please select a state.";
        return;
    }

    if (!district) {
        mandiError.textContent = "Please select a district.";
        return;
    }

    if (!commodity) {
        mandiError.textContent = "Please select a commodity.";
        return;
    }

    mandiStatus.textContent = "Loading mandi prices...";
    mandiRows.innerHTML = `
        <tr>
            <td colspan="6">Loading...</td>
        </tr>
    `;

    try {

        const params = new URLSearchParams({
            state: state,
            district: district,
            commodity: commodity
        });

        const response = await fetch(
            `${API_BASE}/api/mandi/live?${params.toString()}`
        );

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.detail || "Unable to load mandi prices."
            );
        }

        const records = data.records || [];

        if (data.note || data.warning || data.message) {
            mandiNote.textContent = data.note || data.warning || data.message;
        }

        if (records.length === 0) {

            mandiRows.innerHTML = `
                <tr>
                    <td colspan="6">
                        No mandi prices found for
                        ${commodity} in ${district}, ${state}.
                    </td>
                </tr>
            `;

            mandiStatus.textContent = "No prices found.";
            return;
        }

        mandiRows.innerHTML = "";

        records.forEach(record => {

            const row = document.createElement("tr");

            row.innerHTML = `
                <td>${escapeHtml(
                    record.commodity || record.Commodity || commodity
                )}</td>

                <td>${escapeHtml(
                    record.market || record.Market || "-"
                )}</td>

                <td>${escapeHtml(
                    record.min_price ?? record.Min_Price ?? "-"
                )}</td>

                <td>${escapeHtml(
                    record.max_price ?? record.Max_Price ?? "-"
                )}</td>

                <td>${escapeHtml(
                    record.modal_price ?? record.Modal_Price ?? "-"
                )}</td>

                <td>${escapeHtml(
                    record.arrival_date || record.Arrival_Date || record.Date || "-"
                )}</td>
            `;

            mandiRows.appendChild(row);
        });

        mandiStatus.textContent =
            `Showing ${records.length} mandi record(s) for ${district}, ${state}.`;

    } catch (error) {

        console.error("Mandi error:", error);

        mandiRows.innerHTML = `
            <tr>
                <td colspan="6">
                    Unable to load mandi prices.
                </td>
            </tr>
        `;

        mandiError.textContent = error.message;

        mandiStatus.textContent =
            "Mandi service unavailable.";
    }
});


// Basic HTML escaping
function escapeHtml(value) {

    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


// Start
loadStates();