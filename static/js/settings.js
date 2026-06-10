async function setSetting(key) {
    const input = document.getElementById(`input-${key}`);
    const value = parseFloat(input.value);

    if (isNaN(value) || value < 0) {
        alert("enter a valid value");
        return;
    }

    const btn = input.nextElementSibling;
    btn.disabled = true;
    btn.textContent = '...';

    try {
        const response = await fetch('/set_setting', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [key]: value })
        });

        const result = await response.json();

        if (!response.ok) {
            alert(`error: ${result.message || 'failed to update setting'}`);
        } else {
            input.nextElementSibling.nextElementSibling.textContent = value;
            input.value = '';
            input.placeholder = value;
        }
    } catch (err) {
        console.error(err);
        alert('connection error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'set';
    }
}

async function reconcileSettlements() {
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = '...';

    try {
        const response = await fetch('/reconcile_settlements', { method: 'POST' });
        const result = await response.json();
        if (!response.ok) {
            alert(`error: ${result.message || 'failed'}`);
        } else {
            btn.textContent = 'done ✓';
            setTimeout(() => {
                btn.disabled = false;
                btn.textContent = 'run';
            }, 3000);
        }
    } catch (err) {
        alert('connection error');
        btn.disabled = false;
        btn.textContent = 'run';
    }
}