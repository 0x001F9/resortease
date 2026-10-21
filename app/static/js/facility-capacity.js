document.querySelectorAll("[data-capacity-select]").forEach((select) => {
    const form = select.closest("form");
    const partySize = form?.querySelector("[data-party-size-input]");
    const capacityHint = form?.querySelector("[data-capacity-hint]");

    if (!partySize || !capacityHint) return;
    const capacityIsAdvisory = select.hasAttribute("data-capacity-advisory");

    const updateCapacity = () => {
        const capacity = Number(select.selectedOptions[0]?.dataset.capacity || 0);

        if (capacity > 0) {
            if (capacityIsAdvisory) {
                partySize.removeAttribute("max");
                capacityHint.textContent = `Facility capacity: ${capacity} guests. Staff may enter more.`;
            } else {
                partySize.max = capacity;
                capacityHint.textContent = `Maximum capacity: ${capacity} guests.`;
            }
        } else {
            partySize.removeAttribute("max");
            capacityHint.textContent = "No maximum capacity is set for this facility.";
        }
    };

    select.addEventListener("change", updateCapacity);
    updateCapacity();
});
