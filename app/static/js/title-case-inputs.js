(() => {
    const nameFields = new Set([
        "first_name",
        "middle_name",
        "last_name",
        "name",
        "title",
    ])

    const formatInput = (input) => {
        if (!nameFields.has(input.name)) {
            return
        }

        input.value = input.value
            .trim()
            .toLowerCase()
            .replace(/(^|[^\p{L}\p{M}])(\p{L})/gu, (_, separator, letter) => {
                return separator + letter.toUpperCase()
            })
    }

    document.addEventListener("focusout", (event) => {
        if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
            formatInput(event.target)
        }
    })

    document.addEventListener(
        "submit",
        (event) => {
            event.target.querySelectorAll("input, textarea").forEach(formatInput)
        },
        true,
    )
})()
