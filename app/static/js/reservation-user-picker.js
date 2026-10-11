document.querySelectorAll("[data-user-picker]").forEach((picker) => {
    const dialog = picker.querySelector("[data-user-picker-dialog]")
    const openButton = picker.querySelector("[data-user-picker-open]")
    const closeButton = picker.querySelector("[data-user-picker-close]")
    const backdropButton = picker.querySelector("[data-user-picker-backdrop]")
    const searchInput = picker.querySelector("[data-user-picker-search]")
    const resultsList = picker.querySelector("[data-user-picker-results]")
    const status = picker.querySelector("[data-user-picker-status]")
    const selectedId = picker.querySelector("[data-user-picker-id]")
    const selection = picker.querySelector("[data-user-picker-selection]")
    const error = picker.querySelector("[data-user-picker-error]")
    const form = picker.closest("form")
    let debounceTimer
    let activeRequest

    const setStatus = (message) => {
        status.textContent = message
    }

    const searchUsers = async () => {
        activeRequest?.abort()
        activeRequest = undefined
        const query = searchInput.value.trim()
        resultsList.replaceChildren()

        if (!query) {
            setStatus("Enter a name, username, or email to search.")
            return
        }

        activeRequest = new AbortController()
        setStatus("Searching...")

        try {
            const url = new URL(picker.dataset.searchUrl, window.location.origin)
            url.searchParams.set("q", query)
            const response = await fetch(url, { signal: activeRequest.signal })
            if (!response.ok) {
                throw new Error(`User search failed with status ${response.status}.`)
            }
            const data = await response.json()

            if (data.results.length === 0) {
                setStatus("No matching users found.")
                return
            }

            setStatus(
                data.has_more
                    ? "Showing the first 20 matches. Refine your search for more specific results."
                    : `${data.results.length} matching user${data.results.length === 1 ? "" : "s"}.`,
            )
            data.results.forEach((user) => {
                const item = document.createElement("li")
                const button = document.createElement("button")
                button.type = "button"
                button.className = "btn btn-ghost h-auto min-h-0 w-full justify-start py-3 text-left"
                button.addEventListener("click", () => {
                    selectedId.value = user.id
                    selection.textContent = `${user.name} (${user.email})`
                    error?.setAttribute("hidden", "")
                    dialog.close()
                    openButton.focus()
                })

                const details = document.createElement("span")
                details.className = "flex min-w-0 flex-col items-start"
                const name = document.createElement("span")
                name.className = "font-medium"
                name.textContent = user.name
                const account = document.createElement("span")
                account.className = "text-sm text-base-content/70"
                account.textContent = `@${user.username} · ${user.email}`
                details.append(name, account)
                button.append(details)
                item.append(button)
                resultsList.append(item)
            })
        } catch (searchError) {
            if (searchError.name === "AbortError") {
                return
            }
            setStatus("Could not load users. Please try again.")
            console.error(searchError)
        }
    }

    openButton.addEventListener("click", () => {
        dialog.showModal()
        searchInput.focus()
        searchUsers()
    })
    closeButton.addEventListener("click", () => dialog.close())
    backdropButton.addEventListener("click", () => dialog.close())
    searchInput.addEventListener("input", () => {
        activeRequest?.abort()
        resultsList.replaceChildren()
        setStatus(
            searchInput.value.trim()
                ? "Waiting to search..."
                : "Enter a name, username, or email to search.",
        )
        clearTimeout(debounceTimer)
        debounceTimer = setTimeout(searchUsers, 250)
    })
    dialog.addEventListener("close", () => {
        activeRequest?.abort()
        openButton.focus()
    })
    form.addEventListener("submit", (event) => {
        if (selectedId.value) {
            return
        }
        event.preventDefault()
        error?.removeAttribute("hidden")
        openButton.focus()
    })
})
