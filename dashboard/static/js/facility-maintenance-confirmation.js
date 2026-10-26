document.addEventListener("submit", (event) => {
    const form = event.target
    if (!(form instanceof HTMLFormElement)) {
        return
    }

    const confirmationType = form.dataset.maintenanceConfirmation
    if (!confirmationType) {
        return
    }

    const selectedFacility = form.querySelector(
        '[name="facility"] option:checked',
    )
    const facilityIsInMaintenance = selectedFacility
        ? selectedFacility.dataset.maintenanceInProgress === "true"
        : form.dataset.maintenanceInProgress === "true"
    if (!facilityIsInMaintenance) {
        return
    }

    const status = form.querySelector('[name="status"]')?.value
    const isConfirming = confirmationType === "confirm" && status === "confirmed"
    if (confirmationType === "confirm" && !isConfirming) {
        return
    }

    const action = isConfirming ? "confirm" : "create"
    const facilityName =
        selectedFacility?.textContent.trim() || form.dataset.facilityName
    const facilityLabel = facilityName ? ` ${facilityName}` : ""
    if (
        !window.confirm(
            `This facility${facilityLabel} has ongoing maintenance. Are you sure you want to ${action} this reservation?`,
        )
    ) {
        event.preventDefault()
    }
})
