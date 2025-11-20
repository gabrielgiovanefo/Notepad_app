document.addEventListener("DOMContentLoaded", async () => {
    initSearch();
    initNoteToggle();
    initTheme();
    initNotifications();
    await initLanguage();
    initFileUpload();
});

function initNoteToggle() {
    const toggleBtn = document.getElementById("toggle-notes-btn");
    const activeContainer = document.getElementById("active-notes-container");
    const completedContainer = document.getElementById("completed-notes-container");
    
    if (!toggleBtn || !activeContainer || !completedContainer) return;
    
    // Get translations from data attributes
    const viewActiveText = toggleBtn.getAttribute("data-view-active");
    const viewCompletedText = toggleBtn.getAttribute("data-view-completed");
    
    // State to track which view is active
    let showingCompleted = false;
    
    // Function to switch views
    function switchView() {
        showingCompleted = !showingCompleted;
        
        if (showingCompleted) {
            activeContainer.style.display = "none";
            completedContainer.style.display = "block";
            toggleBtn.textContent = viewActiveText;
        } else {
            activeContainer.style.display = "block";
            completedContainer.style.display = "none";
            toggleBtn.textContent = viewCompletedText;
        }
        
        // Clear search when switching views
        document.getElementById("search").value = "";
    }
    
    // Set up button click handler
    toggleBtn.addEventListener("click", switchView);
}

// Search functionality - updated to work with both views
function initSearch() {
    const searchInput = document.getElementById("search");
    if (!searchInput) return;
    
    searchInput.addEventListener("input", () => {
        const query = searchInput.value;
        const isCompletedView = document.getElementById("completed-notes-container").style.display !== "none";
        
        fetch(`/search_notes?q=${encodeURIComponent(query)}&completed=${isCompletedView}`)
            .then(response => {
                if (!response.ok) throw new Error("Search failed");
                return response.text();
            })
            .then(html => {
                if (isCompletedView) {
                    document.getElementById("completed-notes-container").innerHTML = html;
                } else {
                    document.getElementById("active-notes-container").innerHTML = html;
                }
            })
            .catch(error => {
                console.error("Search error:", error);
            });
    });
}


// Theme functionality
function initTheme() {
    const body = document.body;
    const switchButton = document.getElementById("theme-switch");

    if (!switchButton) return;

    // --- Load saved theme on page load ---
    // 'dark' is the name of our class, so we check for that.
    const currentTheme = localStorage.getItem("theme");
    if (currentTheme === "dark") {
        body.classList.add("dark-theme");
    }

    // --- Theme switch button logic ---
    switchButton.addEventListener("click", () => {
        // Toggle the 'dark-theme' class on the body
        body.classList.toggle("dark-theme");

        // Save the new state to localStorage
        if (body.classList.contains("dark-theme")) {
            localStorage.setItem("theme", "dark");
        } else {
            localStorage.setItem("theme", "light");
        }
    });
}

// Simplified Notification functionality
function initNotifications() {
    // Request notification permission
    if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission();
    }
    
    // Function to check for reminders
    function checkForReminders() {
        fetch('/get_reminders')
            .then(response => response.json())
            .then(reminders => {
                if (reminders.length > 0) {
                    reminders.forEach(reminder => {
                        // Show browser notification
                        if ("Notification" in window && Notification.permission === "granted") {
                            new Notification(reminder.title || "Reminder", {
                                body: reminder.content ? 
                                    (reminder.content.length > 200 ? reminder.content.slice(0, 200) + "…" : reminder.content) : 
                                    "No content",
                                icon: "/static/favicon.ico"
                            });
                        }
                        
                        // Show popup
                        showPopup(reminder.id, reminder.title, reminder.content);
                        
                        // Mark as reminded
                        fetch(`/reminded/${reminder.id}`, { method: 'POST' })
                            .catch(error => console.error("Error marking as reminded:", error));
                    });
                }
            })
            .catch(error => console.error("Error checking reminders:", error));
    }
    
    // Check for reminders every minute
    setInterval(checkForReminders, 60000);
    
    // Check immediately on page load
    checkForReminders();
    
    // Function to show popup
    function showPopup(noteId, title, content) {
        fetch('/partials/popup_partial.html')
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
                    fetch(`/reminded/${noteId}`, { method: 'POST' })
                        .catch(error => console.error("Error marking as reminded:", error));
                    closePopup();
                };
                
                popup.querySelector(".mark-done").onclick = () => {
                    fetch(`/done/${noteId}`, { method: 'POST' })
                        .then(() => fetch(`/reminded/${noteId}`, { method: 'POST' }))
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

// Consolidated file upload functionality
function initFileUpload() {
    // Check for both dropzone and file-attachment-area implementations
    const dropzones = document.querySelectorAll(".dropzone");
    const fileAttachmentAreas = document.querySelectorAll('.file-attachment-area');
    
    // Initialize dropzones if they exist
    if (dropzones.length > 0) {
        initDropzones();
    }
    
    // Initialize file attachment areas if they exist
    if (fileAttachmentAreas.length > 0) {
        initFileAttachmentAreas();
    }
    
    function initDropzones() {
        document.querySelectorAll(".dropzone").forEach(zone => {
            const input = zone.querySelector(".dropzone-input");
            zone.addEventListener("click", () => input.click());
            input.addEventListener("change", (e) => {
                if (e.target.files.length) uploadFile(zone.dataset.noteId, e.target.files[0], zone);
            });

            zone.addEventListener("dragover", (e) => {
                e.preventDefault();
                zone.classList.add("dragover");
            });
            zone.addEventListener("dragleave", (e) => {
                zone.classList.remove("dragover");
            });
            zone.addEventListener("drop", (e) => {
                e.preventDefault();
                zone.classList.remove("dragover");
                const file = e.dataTransfer.files[0];
                if (file) uploadFile(zone.dataset.noteId, file, zone);
            });
        });
    }

    function initFileAttachmentAreas() {
        document.querySelectorAll('.file-attachment-area').forEach(zone => {
            const dropArea = zone.querySelector('.drop-zone');
            const fileInput = zone.querySelector('.file-input');
            const noteId = fileInput.getAttribute('data-note-id');
            
            // Prevent default drag behaviors
            ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
                dropArea.addEventListener(eventName, preventDefaults, false);
                document.body.addEventListener(eventName, preventDefaults, false);
            });
            
            // Highlight drop area when item is dragged over it
            ['dragenter', 'dragover'].forEach(eventName => {
                dropArea.addEventListener(eventName, highlight, false);
            });
            
            ['dragleave', 'drop'].forEach(eventName => {
                dropArea.addEventListener(eventName, unhighlight, false);
            });
            
            // Handle dropped files
            dropArea.addEventListener('drop', handleDrop, false);
            
            // Handle file selection via input
            fileInput.addEventListener('change', function() {
                handleFiles(this.files, noteId);
            });
        });
    }

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
    function highlight(e) {
        e.currentTarget.classList.add('drag-over');
    }
    
    function unhighlight(e) {
        e.currentTarget.classList.remove('drag-over');
    }
    
    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        const noteId = e.currentTarget.closest('.file-attachment-area').id.replace('file-drop-', '');
        handleFiles(files, noteId);
    }
    
    function handleFiles(files, noteId) {
        if (files.length === 0) return;
        
        const progressContainer = document.getElementById(`upload-progress-${noteId}`);
        const progressBar = progressContainer.querySelector('.progress-fill');
        const progressText = progressContainer.querySelector('.progress-text');
        const attachedFilesContainer = document.getElementById(`attached-files-${noteId}`);
        
        // Show progress bar
        progressContainer.style.display = 'block';
        progressBar.style.width = '0%';
        progressText.textContent = 'Uploading...';
        
        // Create FormData for the upload
        const formData = new FormData();
        for (let i = 0; i < files.length; i++) {
            formData.append('file', files[i]);
        }
        
        // Upload files
        fetch(`/upload_file/${noteId}`, {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.ok) {
                // Update progress bar
                progressBar.style.width = '100%';
                progressText.textContent = 'Upload complete!';
                
                // Add file to the attached files list
                const fileItem = document.createElement('div');
                fileItem.className = 'file-item';
                fileItem.setAttribute('data-file-id', data.file_id);
                
                const fileName = document.createElement('span');
                fileName.className = 'file-name';
                fileName.textContent = data.filename;
                
                const downloadLink = document.createElement('a');
                downloadLink.className = 'download-btn';
                downloadLink.href = `/download_file/${data.file_id}`;
                downloadLink.title = 'Download';
                downloadLink.innerHTML = `
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="7 10 12 15 17 10"></polyline>
                        <line x1="12" y1="15" x2="12" y2="3"></line>
                    </svg>
                `;
                
                fileItem.appendChild(fileName);
                fileItem.appendChild(downloadLink);
                attachedFilesContainer.appendChild(fileItem);
                
                // Hide progress bar after a short delay
                setTimeout(() => {
                    progressContainer.style.display = 'none';
                }, 1500);
            } else {
                throw new Error(data.error || 'Upload failed');
            }
        })
        .catch(error => {
            console.error('Error uploading file:', error);
            progressBar.style.width = '0%';
            progressText.textContent = 'Upload failed. Please try again.';
            
            // Hide progress bar after a short delay
            setTimeout(() => {
                progressContainer.style.display = 'none';
            }, 3000);
        });
    }

    async function uploadFile(noteId, file, zone) {
        const fd = new FormData();
        fd.append("file", file);
        zone.classList.add("uploading");
        try {
            const res = await fetch(`/upload_file/${noteId}`, { method: "POST", body: fd });
            const data = await res.json();
            if (res.ok && data.ok) {
                // append file to UI
                const filesDiv = zone.parentElement.querySelector(".note-files");
                if (filesDiv) {
                    const d = document.createElement("div");
                    d.className = "file-entry";
                    const a = document.createElement("a");
                    a.href = `/download_file/${data.file_id || ""}`; // if server returns file id, use it
                    a.textContent = data.filename;
                    // if server returned file id, set correct href
                    if (data.file_id) a.href = `/download_file/${data.file_id}`;
                    filesDiv.prepend(d);
                    d.appendChild(a);
                } else {
                    // optionally refresh page
                    location.reload();
                }
            } else {
                alert(data.error || "Upload failed");
            }
        } catch (err) {
            console.error(err);
            alert("Upload error");
        } finally {
            zone.classList.remove("uploading");
        }
    }
}