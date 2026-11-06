(() => {
    const appTimeZone = document.documentElement.dataset.timezone;
    if (!appTimeZone) {
        throw new Error("The application timezone is missing from the page.");
    }

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
        timeZone: appTimeZone,
    });
    const dateTimePartsFormat = new Intl.DateTimeFormat("en-US", {
        timeZone: appTimeZone,
        calendar: "gregory",
        numberingSystem: "latn",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
    });

    function getDateTimeParts(date) {
        return Object.fromEntries(
            dateTimePartsFormat.formatToParts(date)
                .filter(({ type }) => type !== "literal")
                .map(({ type, value }) => [type, Number(value)]),
        );
    }

    function getWallTimeTimestamp({ year, month, day, hour, minute }) {
        const date = new Date(0);
        date.setUTCFullYear(year, month - 1, day);
        date.setUTCHours(hour, minute, 0, 0);
        return date.getTime();
    }

    function parseLocalDateTime(value) {
        const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
        if (!match) {
            return null;
        }

        const [, year, month, day, hour, minute] = match.map(Number);
        const requestedParts = { year, month, day, hour, minute };
        const wallTimeTimestamp = getWallTimeTimestamp(requestedParts);
        let timestamp = wallTimeTimestamp;
        for (let attempt = 0; attempt < 4; attempt += 1) {
            const actualWallTime = getWallTimeTimestamp(
                getDateTimeParts(new Date(timestamp)),
            );
            const adjustment = wallTimeTimestamp - actualWallTime;
            timestamp += adjustment;
            if (adjustment === 0) {
                break;
            }
        }

        const resolvedParts = getDateTimeParts(new Date(timestamp));
        if (
            Object.keys(requestedParts).some(
                (part) => requestedParts[part] !== resolvedParts[part],
            )
        ) {
            return null;
        }

        return {
            timestamp,
            date: `${match[1]}-${match[2]}-${match[3]}`,
            time: `${match[4]}:${match[5]}`,
        }
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
        const allowExtraHours = form.dataset.allowExtraHours === "true";
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

        const packageEndTimestamp = startsAt.timestamp + duration;
        let endTimestamp = packageEndTimestamp;
        if (allowExtraHours) {
            const requestedEnd = parseLocalDateTime(endInput.value);
            if (!requestedEnd) {
                endDisplay.textContent = "Choose an end date and time";
                return null;
            }
            endTimestamp = requestedEnd.timestamp;
            const extraDuration = endTimestamp - packageEndTimestamp;
            const hour = 60 * 60 * 1000;
            if (extraDuration < 0 || extraDuration % hour !== 0) {
                endDisplay.textContent = endDateTimeFormat.format(
                    new Date(endTimestamp),
                );
                return {
                    error: "The end time must be after the package and extensions must be in full-hour increments.",
                };
            }
        } else {
            const endParts = getDateTimeParts(new Date(packageEndTimestamp));
            endInput.value = `${endParts.year}-${String(endParts.month).padStart(2, "0")}-${String(endParts.day).padStart(2, "0")}T${String(endParts.hour).padStart(2, "0")}:${String(endParts.minute).padStart(2, "0")}`;
        }
        const endDate = new Date(endTimestamp);

        if (
            (selectedPackage === "morning" && startsAt.time !== "08:00")
            || (selectedPackage === "evening" && startsAt.time !== "19:00")
        ) {
            endDisplay.textContent = endDateTimeFormat.format(endDate);
            return { error: "Morning rates start at 8 AM; evening rates start at 7 PM." };
        }

        endDisplay.textContent = endDateTimeFormat.format(endDate);
        return {
            selectedPackage,
            startsAt,
            days: isDailyRate ? Number(daysInput.value) : 1,
            duration: endTimestamp - startsAt.timestamp,
        };
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

    function selectedExtraHourAmount(form, selected) {
        if (!selected || selected.error) {
            return null;
        }
        const option = form.elements.namedItem("facility")?.selectedOptions[0];
        const rateValue = option?.dataset.extraHourRate;
        const rate = rateValue ? Number(rateValue) : NaN;
        const packageDuration = {
            "24hours": 24 * 60 * 60 * 1000 * selected.days,
            "22hours": 22 * 60 * 60 * 1000,
            morning: 9 * 60 * 60 * 1000,
            evening: 11 * 60 * 60 * 1000,
        }[selected.selectedPackage];
        const extraDuration = selected.duration - packageDuration;
        const hour = 60 * 60 * 1000;
        if (extraDuration < 0 || extraDuration % hour !== 0) {
            return null;
        }
        if (extraDuration === 0) {
            return 0;
        }
        if (!Number.isFinite(rate) || rate <= 0) {
            return null;
        }
        return Math.round(rate * 100) * (extraDuration / hour);
    }

    function updateRateLabels(form) {
        const facility = form.elements.namedItem("facility");
        const option = facility?.selectedOptions[0];
        const extraHourRateLabel = form.querySelector(
            "[data-price-extra-hour-rate]",
        );
        if (extraHourRateLabel) {
            const rateValue = option?.dataset.extraHourRate;
            const rate = rateValue ? Number(rateValue) : NaN;
            extraHourRateLabel.textContent = Number.isFinite(rate) && rate > 0
                ? `${money.format(rate)} per hour`
                : "Not available";
        }
        const rateKeys = {
            "24hours": "rate24Hours",
            "22hours": "rate22Hours",
            morning: "rateMorning",
            evening: "rateEvening",
        };

        Object.entries(rateKeys).forEach(([ratePackage, rateKey]) => {
            const label = form.querySelector(
                `[data-rate-price-for="${ratePackage}"]`,
            );
            if (!label) {
                return;
            }

            const rateValue = option?.dataset[rateKey];
            const rate = rateValue === undefined || rateValue === ""
                ? NaN
                : Number(rateValue);
            label.textContent = Number.isFinite(rate) && rate >= 0
                ? money.format(rate)
                : "Not available";
        });
    }

    function updatePriceSummary(form) {
        const preview = form.querySelector("[data-price-preview]");
        if (!preview) {
            return;
        }

        updateRateLabels(form);
        const selected = updateReservationEnd(form);
        const baseAmount = selectedRate(form, selected);
        const extraHourAmount = selectedExtraHourAmount(form, selected);
        const rawAmount = baseAmount !== null && extraHourAmount !== null
            ? baseAmount + extraHourAmount
            : null;
        const discountInput = form.elements.namedItem("discount");
        const discountValue = discountInput.value.trim() || "0";
        const discountIsValid = /^\d+(\.\d{1,2})?$/.test(discountValue);
        const discountCents = discountIsValid
            ? Math.round(Number(discountValue) * 100)
            : null;

        preview.querySelector("[data-price-raw]").textContent = (
            baseAmount === null ? "—" : money.format(baseAmount / 100)
        );
        preview.querySelector(
            "[data-price-extra-hour-amount]",
        ).textContent = (
            extraHourAmount === null
                ? "—"
                : money.format(extraHourAmount / 100)
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
                        ? "The selected rate or extra-hour rate is unavailable, or the end time is not a full-hour increment."
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

        ["facility", "days", "discount", "ends_at"].forEach((name) => {
            if (!form.elements.namedItem(name)) {
                return;
            }
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
