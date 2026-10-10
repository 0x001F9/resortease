(() => {
    const money = new Intl.NumberFormat("en-PH", {
        style: "currency",
        currency: "PHP",
    });
    const endDateTimeFormat = new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
        timeZone: "UTC",
    });
    function parseLocalDateTime(value) {
        const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
        if (!match) {
            return null;
        }

        const [, year, month, day, hour, minute] = match.map(Number);
        return {
            timestamp: Date.UTC(year, month - 1, day, hour, minute),
            date: `${match[1]}-${match[2]}-${match[3]}`,
            time: `${match[4]}:${match[5]}`,
        };
    }

    function updateReservationEnd(form) {
        const selectedPackage = form.querySelector(
            'input[name="rate_package"]:checked',
        )?.value;
        const daysField = form.querySelector("[data-days-field]");
        const daysInput = form.querySelector("[data-days-input]");
        const startPicker = form.querySelector("[data-start-picker]");
        const startHelp = form.querySelector("[data-start-help]");
        const startInput = form.elements.namedItem("starts_at");
        const endInput = form.elements.namedItem("ends_at");
        const endDisplay = form.querySelector("[data-end-display]");
        const fixedStartTimes = {
            morning: { value: "08:00", label: "8:00 AM" },
            evening: { value: "19:00", label: "7:00 PM" },
        };
        const fixedStart = fixedStartTimes[selectedPackage];
        const fixedStartTime = fixedStart?.value;
        const desiredPickerType = fixedStartTime ? "date" : "datetime-local";

        startPicker.disabled = !selectedPackage;

        if (startPicker.type !== desiredPickerType) {
            const previousValue = startPicker.value;
            const previousDate = startPicker.type === "date"
                ? previousValue
                : previousValue.slice(0, 10);
            const previousTime = startPicker.type === "datetime-local"
                ? previousValue.slice(11, 16)
                : startPicker.dataset.lastTime || "09:00";

            if (startPicker.type === "datetime-local" && previousTime) {
                startPicker.dataset.lastTime = previousTime;
            }
            startPicker.type = desiredPickerType;
            startPicker.value = desiredPickerType === "date"
                ? previousDate
                : (previousDate ? `${previousDate}T${previousTime}` : "");
        }

        startPicker.dataset.fixedTime = fixedStartTime || "";
        startHelp.textContent = !selectedPackage
            ? "Choose a rate to enable the start date and time."
            : fixedStartTime
            ? `Start time is fixed at ${fixedStart.label}. Choose the date only.`
            : "Choose a start date and time.";
        startInput.value = startPicker.value
            ? (fixedStartTime
                ? `${startPicker.value}T${fixedStartTime}`
                : startPicker.value)
            : "";

        const startsAt = parseLocalDateTime(
            startInput.value,
        );

        const isDailyRate = selectedPackage === "24hours";
        daysField.hidden = !isDailyRate;
        daysInput.required = isDailyRate;

        if (!selectedPackage || !startsAt) {
            endInput.value = "";
            endDisplay.textContent = "Choose a rate and start time";
            return null;
        }

        let duration = 0;
        if (isDailyRate) {
            const days = Number(daysInput.value);
            if (!Number.isSafeInteger(days) || days < 1) {
                endInput.value = "";
                endDisplay.textContent = "Choose a valid number of days";
                return null;
            }
            duration = days * 24 * 60 * 60 * 1000;
        } else if (selectedPackage === "22hours") {
            duration = 22 * 60 * 60 * 1000;
        } else if (selectedPackage === "morning") {
            duration = 9 * 60 * 60 * 1000;
        } else if (selectedPackage === "evening") {
            duration = 11 * 60 * 60 * 1000;
        } else {
            endInput.value = "";
            endDisplay.textContent = "Choose a rate and start time";
            return null;
        }

        const endTimestamp = startsAt.timestamp + duration;
        const endDate = new Date(endTimestamp);
        endInput.value = [
            endDate.getUTCFullYear(),
            String(endDate.getUTCMonth() + 1).padStart(2, "0"),
            String(endDate.getUTCDate()).padStart(2, "0"),
        ].join("-") + `T${String(endDate.getUTCHours()).padStart(2, "0")}:${String(endDate.getUTCMinutes()).padStart(2, "0")}`;

        if (
            (selectedPackage === "morning" && startsAt.time !== "08:00")
            || (selectedPackage === "evening" && startsAt.time !== "19:00")
        ) {
            endDisplay.textContent = endDateTimeFormat.format(endDate);
            return { error: "Morning rates start at 8 AM; evening rates start at 7 PM." };
        }

        endDisplay.textContent = endDateTimeFormat.format(endDate);
        return { selectedPackage, startsAt, days: isDailyRate ? Number(daysInput.value) : 1 };
    }

    function selectedRate(form, selected) {
        const facility = form.elements.namedItem("facility");
        const option = facility?.selectedOptions[0];
        if (!option || !selected || selected.error) {
            return null;
        }

        const rateKey = {
            "24hours": "rate24Hours",
            "22hours": "rate22Hours",
            morning: "rateMorning",
            evening: "rateEvening",
        }[selected.selectedPackage];

        const rateValue = option.dataset[rateKey];
        if (!rateValue) {
            return null;
        }

        const rate = Number(rateValue);
        return Number.isFinite(rate) && rate >= 0
            ? Math.round(rate * 100) * selected.days
            : null;
    }

    function updatePriceSummary(form) {
        const preview = form.querySelector("[data-price-preview]");
        if (!preview) {
            return;
        }

        const selected = updateReservationEnd(form);
        const rawAmount = selectedRate(form, selected);
        const discountInput = form.elements.namedItem("discount");
        const discountValue = discountInput.value.trim() || "0";
        const discountIsValid = /^\d+(\.\d{1,2})?$/.test(discountValue);
        const discountCents = discountIsValid
            ? Math.round(Number(discountValue) * 100)
            : null;

        preview.querySelector("[data-price-raw]").textContent = (
            rawAmount === null ? "—" : money.format(rawAmount / 100)
        );
        preview.querySelector("[data-price-discount]").textContent = (
            discountCents === null ? "—" : `−${money.format(discountCents / 100)}`
        );

        const total = preview.querySelector("[data-price-total]");
        const status = preview.querySelector("[data-price-status]");
        if (rawAmount === null) {
            total.textContent = "—";
            status.textContent = selected?.error
                || (!form.elements.namedItem("facility").value
                    ? "Choose a facility to preview the amount."
                    : selected
                        ? "That rate is not configured for this facility."
                        : "Choose a rate and start time to preview the amount.");
        } else if (discountCents === null) {
            total.textContent = "—";
            status.textContent = "Enter a valid discount amount.";
        } else if (discountCents > rawAmount) {
            total.textContent = "—";
            status.textContent = "Discount cannot exceed the raw amount.";
        } else {
            total.textContent = money.format((rawAmount - discountCents) / 100);
            status.textContent = "Estimated from the selected facility rate and discount.";
        }
    }

    document.querySelectorAll("form").forEach((form) => {
        if (!form.querySelector("[data-price-preview]")) {
            return;
        }

        ["facility", "days", "discount"].forEach((name) => {
            form.elements.namedItem(name).addEventListener("input", () => updatePriceSummary(form));
            form.elements.namedItem(name).addEventListener("change", () => updatePriceSummary(form));
        });
        const startPicker = form.querySelector("[data-start-picker]");
        ["input", "change"].forEach((eventName) => {
            startPicker.addEventListener(eventName, () => updatePriceSummary(form));
        });
        form.querySelectorAll('input[name="rate_package"]').forEach((radio) => {
            radio.addEventListener("change", () => updatePriceSummary(form));
        });
        updatePriceSummary(form);
    });
})();
