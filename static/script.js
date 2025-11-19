// Consolidated DOMContentLoaded event listener
document.addEventListener("DOMContentLoaded", async () => {
    // Send timezone first and wait for it to complete
    await sendTimezoneToServer();
    
    // Then initialize all functionality
    initSearch();
    initTheme();
    initNotifications();
    await initLanguage();
});

// Search functionality - consolidated
function initSearch() {
    const notesContainer = document.getElementById("notes-container");
    
    // Helper function for search
    function setupSearch(searchId, completed) {
        const searchElement = document.getElementById(searchId);
        if (!searchElement) return;
        
        searchElement.addEventListener("input", () => {
            const query = searchElement.value;
            fetch(`/search_notes?q=${encodeURIComponent(query)}&completed=${completed}`)
                .then(response => {
                    if (!response.ok) throw new Error("Search failed");
                    return response.text();
                })
                .then(html => {
                    notesContainer.innerHTML = html;
                })
                .catch(error => {
                    console.error("Search error:", error);
                    // Optionally show user feedback
                });
        });
    }
    
    // Setup both search inputs
    setupSearch("search", false);
    setupSearch("completed_search", true);
}

// Theme functionality
function initTheme() {
    const themeLink = document.getElementById("theme-link"); 
    const switchButton = document.getElementById("theme-switch");
    
    if (!themeLink || !switchButton) return;
    
    // Theme type definitions (desktop ↔ mobile pairs)
    const themes = {
        default: {
            desktop: "/static/style1.css",
            mobile: "/static/style1_mobile.css"
        },
        matrix: {
            desktop: "/static/style2.css",
            mobile: "/static/style2_mobile.css"
        },
        light: {
            desktop: "/static/style3.css",
            mobile: "/static/style3_mobile.css"
        }
    };
    
    const themeOrder = ["matrix", "light"];
    
    // Detect mobile device or narrow portrait ratio
    function isMobileDevice() {
        const ua = navigator.userAgent;
        const isTouch =
            /Mobi|Android|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua);
        const aspectRatio = window.innerWidth / window.innerHeight;
        const isPortraitPhone = aspectRatio < 0.7; // ~9:16 or narrower
        return isTouch || isPortraitPhone;
    }
    
    // Load saved theme (defaults to matrix)
    let currentTheme = localStorage.getItem("themeName") || "matrix";
    
    function applyTheme(name) {
        if (!themes[name]) name = "matrix";
        const selected = isMobileDevice() ? themes[name].mobile : themes[name].desktop;
        themeLink.href = selected;
        localStorage.setItem("themeName", name);
    }
    
    // Initial apply
    applyTheme(currentTheme);
    
    // Theme switch button
    switchButton.addEventListener("click", () => {
        const idx = themeOrder.indexOf(currentTheme);
        const next = (idx + 1) % themeOrder.length;
        currentTheme = themeOrder[next];
        applyTheme(currentTheme);
    });
    
    // Recheck if user rotates screen or resizes window
    window.addEventListener("resize", () => {
        applyTheme(currentTheme);
    });
}

// Timezone functionality - consolidated
function sendTimezoneToServer() {
    const offset = new Date().getTimezoneOffset();
    return fetch('/set_timezone', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ offset: offset }),
        credentials: 'same-origin'
    })
    .then(response => {
        if (!response.ok) throw new Error("Failed to set timezone");
        return response.json();
    })
    .catch(error => {
        console.error("Error setting timezone:", error);
        throw error; // Re-throw to maintain the rejection
    });
}

// Notification functionality
function initNotifications() {
    // First, check if the browser even supports EventSource
    if (!window.EventSource) {
        console.error("Your browser does not support Server-Sent Events. Notifications will not work.");
        return;
    }

    // Create helper function for fetch operations
    function safeFetch(url, options = {}) {
        return fetch(url, {
            credentials: 'same-origin',
            ...options
        })
        .then(response => {
            if (!response.ok) throw new Error(`Request failed: ${response.status}`);
            return response;
        });
    }
    
    function requestNotificationPermission() {
        if ("Notification" in window && Notification.permission === "default") {
            Notification.requestPermission().then(permission => {
                console.log("Notification permission:", permission);
            });
        }
    }
    
    function showPopup(noteId, title, content) {
    // Show browser notification if permission is granted
    if ("Notification" in window && Notification.permission === "granted") {
        new Notification(title || "Reminder", {
            body: content ? (content.length > 200 ? content.slice(0, 200) + "…" : content) : "No content",
            icon: "/static/favicon.ico"
        });
    }

    fetch('partials/popup_partial.html')
        .then(response => response.text())
        .then(html => {
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = html;
            
            const popup = tempDiv.querySelector('.reminder-popup');
            
            popup.querySelector('#popup-title').textContent = title || "Reminder";
            const contentText = content ? (content.length > 200 ? content.slice(0, 200) + "…" : content) : "No content";
            popup.querySelector('#popup-content').textContent = contentText;
            
            document.body.appendChild(popup);
            
            const closePopup = () => popup.remove();
            
            popup.querySelector(".dismiss").onclick = () => {
                safeFetch(`/reminded/${noteId}`, { method: 'POST' })
                    .catch(error => console.error("Error marking as reminded:", error));
                closePopup();
            };
            
            popup.querySelector(".mark-done").onclick = () => {
                safeFetch(`/done/${noteId}`, { method: 'POST' })
                    .then(() => safeFetch(`/reminded/${noteId}`, { method: 'POST' }))
                    .catch(error => console.error("Error marking note as done:", error))
                    .finally(closePopup);
            };
            
            // Auto-close after 2 minutes
            setTimeout(closePopup, 120000);
        })
        .catch(error => {
            console.error("Failed to load popup template:", error);
        });
}
    
    function setupNotifications() {
        console.log("Attempting to connect to /notifications for Server-Sent Events.");
        const eventSource = new EventSource('/notifications');
    
        eventSource.onopen = function() {
            console.log("Successfully connected to the notification stream.");
        };
    
        eventSource.onmessage = function(event) {
            const message = JSON.parse(event.data);
            
            if (message.type === 'connected') {
                console.log("Notification stream connected successfully");
            } else if (message.type === 'heartbeat') {
                // Just a heartbeat to keep the connection alive
                console.log("Heartbeat received");
            } else if (message.type === 'reminders') {
                console.log("Received reminders from server:", message.data);
                message.data.forEach(reminder => {
                    showPopup(reminder.id, reminder.title, reminder.content);
                    safeFetch(`/reminded/${reminder.id}`, { method: 'POST' })
                        .catch(error => console.error("Error marking as reminded:", error));
                });
            } else if (message.type === 'error') {
                console.error("Error from notification stream:", message.message);
            }
        };
    
        eventSource.onerror = function(err) {
            console.error("EventSource connection failed.", err);
            console.error("EventSource readyState:", eventSource.readyState);
            
            // Log common causes for the user to check
            console.error(
                "This error is usually caused by one of the following:\n" +
                "1. The server endpoint '/notifications' does not exist (404 Not Found).\n" +
                "2. The server returned an error status (e.g., 500 Internal Server Error).\n" +
                "3. The server did not respond with 'Content-Type: text/event-stream'.\n" +
                "4. A network issue or authentication problem.\n" +
                "Please check the 'Network' tab in your browser's developer tools for more details on the failing request."
            );

            eventSource.close();
            
            // Wait 5 seconds before trying to reconnect
            console.log("Will attempt to reconnect in 5 seconds...");
            setTimeout(setupNotifications, 5000);
        };
    }
    
    // Initialize notifications
    requestNotificationPermission();
    setupNotifications();
}

// Language functionality
async function initLanguage() {
    let CLIENT_T = {};
    
    async function loadTranslations() {
        try {
            const res = await fetch("/static/translations.json", { cache: "no-store" });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            CLIENT_T = await res.json();
            console.log("Loaded translations:", CLIENT_T);
            return true;
        } catch (err) {
            console.error("Failed to load translations.json", err);
            return false;
        }
    }
    
    // set and apply
    function applyClientLanguage(lang) {
        if (!CLIENT_T[lang]) lang = "pt";
        localStorage.setItem("lang", lang);
    
        const themeBtn = document.getElementById("theme-switch");
        if (themeBtn) themeBtn.textContent = CLIENT_T[lang].switch_theme;
    
        const searchInput = document.getElementById("search");
        if (searchInput) searchInput.placeholder = CLIENT_T[lang].search_notes;
    
        const reminderLabel = document.querySelector("label[for='reminder_at']");
        if (reminderLabel) reminderLabel.textContent = CLIENT_T[lang].remind_at;
    }
    
    // Load translations first
    const translationsLoaded = await loadTranslations();
    if (!translationsLoaded) return;
    
    const stored = localStorage.getItem("lang") || "{{ current_lang|default('pt') }}";
    applyClientLanguage(stored);
    
    // wire language selector
    const langSelect = document.getElementById("lang-switch");
    if (langSelect) {
        // preselect if not already
        if (!langSelect.value) langSelect.value = localStorage.getItem("lang") || stored;
    
        langSelect.addEventListener("change", (e) => {
            const newLang = e.target.value;
            applyClientLanguage(newLang);
    
            // notify server
            fetch("/set_language", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ lang: newLang }),
                credentials: "same-origin"
            })
            .then(resp => {
                if (!resp.ok) throw new Error("language set failed");
                // reload so server-rendered partials reflect language
                window.location.reload();
            })
            .catch(err => {
                console.error("Language change failed", err);
            });
        });
    }
}