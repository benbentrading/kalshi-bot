
var socket = io();

socket.on('connect', function() {
    console.log("socket connected, id:", socket.id);
});

socket.on('connect_error', function(err) {
    console.error("connection error:", err);
});

socket.on("batch_update", (updates) => {
    updates.forEach(update => {
        const { event_type, data } = update;
        if (event_type === "market_update") {
            updateMarket(data);
        }
    });
});

function updateMarket(data) {
    const marketElem = document.getElementById(data.kalshi_ticker);
    if (!marketElem) return;

    // market element attributes
    const kalshiBidPx     = marketElem.querySelector('[data-field="kalshi-bid-px"]');
    const kalshiAskPx     = marketElem.querySelector('[data-field="kalshi-ask-px"]');
    const kalshiBidCtx    = marketElem.querySelector('[data-field="kalshi-bid-ctx"]');
    const kalshiAskCtx    = marketElem.querySelector('[data-field="kalshi-ask-ctx"]');
    const kalshiUpdated   = marketElem.querySelector('[data-field="kalshi-updated"]');
    const lastPx          = marketElem.querySelector('[data-field="last-px"]');
    const vegasBidPx      = marketElem.querySelector('[data-field="vegas-bid-px"]');
    const vegasAskPx      = marketElem.querySelector('[data-field="vegas-ask-px"]');
    const vegasUpdated    = marketElem.querySelector('[data-field="vegas-updated"]');
    const botBidPx        = marketElem.querySelector('[data-field="bot-bid-px"]');
    const botAskPx        = marketElem.querySelector('[data-field="bot-ask-px"]');
    const botBidCtx       = marketElem.querySelector('[data-field="bot-bid-ctx"]');
    const botAskCtx       = marketElem.querySelector('[data-field="bot-ask-ctx"]');
    const botUpdated      = marketElem.querySelector('[data-field="bot-updated"]');

    const kalshiYesBid    = data.kalshi_yes_best_bid     != null ? parseFloat(data.kalshi_yes_best_bid)     : null;
    const kalshiNoBid     = data.kalshi_no_best_bid      != null ? parseFloat(data.kalshi_no_best_bid)      : null;
    const kalshiYesBidCtx = data.kalshi_yes_best_bid_ctx != null ? parseFloat(data.kalshi_yes_best_bid_ctx) : null;
    const kalshiNoBidCtx  = data.kalshi_no_best_bid_ctx  != null ? parseFloat(data.kalshi_no_best_bid_ctx)  : null;
    const vegasYesBid     = data.vegas_yes_bid           != null ? parseFloat(data.vegas_yes_bid)           : null;
    const vegasNoBid      = data.vegas_no_bid            != null ? parseFloat(data.vegas_no_bid)            : null;

    // kalshi row
    if (kalshiBidPx)   kalshiBidPx.textContent   = kalshiYesBid    != null ? kalshiYesBid.toFixed(2)          : "—";
    if (kalshiAskPx)   kalshiAskPx.textContent   = kalshiNoBid     != null ? (1 - kalshiNoBid).toFixed(2)     : "—";
    if (kalshiBidCtx)  kalshiBidCtx.textContent  = kalshiYesBidCtx != null ? kalshiYesBidCtx.toFixed(0)       : "—";
    if (kalshiAskCtx)  kalshiAskCtx.textContent  = kalshiNoBidCtx  != null ? kalshiNoBidCtx.toFixed(0)        : "—";
    if (kalshiUpdated) kalshiUpdated.textContent = data.kalshi_last_update ?? "—";
    if (lastPx)        lastPx.textContent        = `last px: ${data.kalshi_last_px} at ${data.kalshi_last_trade_time}`;

    // vegas row
    if (vegasBidPx)  vegasBidPx.textContent  = vegasYesBid != null ? vegasYesBid.toFixed(2)           : "—";
    if (vegasAskPx) {
        const vegasAsk = vegasNoBid != null ? (1 - vegasNoBid) : null;
        vegasAskPx.textContent = vegasAsk != null ? vegasAsk.toFixed(2) : "—";
    }
    if (vegasUpdated) vegasUpdated.textContent = data.boltodds_last_update ?? "—";

    // bot row
    if (botBidPx)        botBidPx.textContent        = data.yes_order.px  != null ? parseFloat(data.yes_order.px).toFixed(2)              : "—";
    if (botAskPx)        botAskPx.textContent        = data.no_order.px   != null ? (1 - parseFloat(data.no_order.px)).toFixed(2)         : "—";
    if (botBidCtx)       botBidCtx.textContent       = data.yes_order.ctx ?? "—";
    if (botAskCtx)       botAskCtx.textContent       = data.no_order.ctx  ?? "—";
    if (botUpdated)      botUpdated.textContent      = data.kalshi_last_update ?? "—";

    // position + pnl
    const position  = data.position_ctx;
    const costBasis = data.cost_basis_per_share;
    const pnl       = data.realized_pnl;

    if (position != null && position !== 0 || pnl != 0) {
        let posElem = marketElem.querySelector('[data-field="position"]');
        if (!posElem) {
            posElem = document.createElement('small');
            posElem.className = 'kalshi-position';
            posElem.setAttribute('data-field', 'position');
            const desc = marketElem.querySelector('.kalshi-description');
            desc.insertAdjacentElement('afterend', posElem);
        }
        posElem.textContent = `position: ${parseFloat(position).toFixed(2)} @ ${costBasis != null ? parseFloat(costBasis).toFixed(2) : "—"}`;

        let pnlElem = marketElem.querySelector('[data-field="pnl"]');
        if (!pnlElem) {
            pnlElem = document.createElement('small');
            pnlElem.className = 'kalshi-pnl';
            pnlElem.setAttribute('data-field', 'pnl');
            posElem.insertAdjacentElement('afterend', pnlElem);
        }
        pnlElem.textContent = `pnl: $${pnl != null ? parseFloat(pnl).toFixed(2) : "—"}`;
    } else {
        const posElem = marketElem.querySelector('[data-field="position"]');
        const pnlElem = marketElem.querySelector('[data-field="pnl"]');
        if (posElem) posElem.remove();
        if (pnlElem) pnlElem.remove();
    }

    // live badge + border
    if (data.trading_venue === 'prod') {
        marketElem.classList.add('market-live');
        let badge = marketElem.querySelector('.live-badge');
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'live-badge';
            badge.textContent = 'LIVE';
            marketElem.insertBefore(badge, marketElem.firstChild);
        }
    } else {
        marketElem.classList.remove('market-live');
        const badge = marketElem.querySelector('.live-badge');
        if (badge) badge.remove();
    }

    // get count of live markets
    const eventGroup = marketElem.closest('.event-group');
    if (eventGroup) {
        const liveCount = eventGroup.querySelectorAll('.market-live').length;
        const liveSpan = eventGroup.querySelector('.live-count');
        if (liveSpan) {
            liveSpan.textContent = liveCount > 0 ? ` · ${liveCount} live` : '';
        }
    }

    // put live markets first in each group
    const eventMarkets = marketElem.closest('.event-markets');
    if (eventMarkets) {
        [...eventMarkets.children].sort((a, b) => {
            const aLive = a.querySelector('.market-live') !== null ? 0 : 1;
            const bLive = b.querySelector('.market-live') !== null ? 0 : 1;
            return aLive - bLive;
        }).forEach(el => eventMarkets.appendChild(el));
    }
}



/******************************************
 * SETTER FUNCTIONS (calls flask routes)  *
*******************************************/
async function setTradingVenue(kalshiTicker, tradingVenue) {
    try {
        const response = await fetch('/set_market_trading_venue', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                kalshi_market_ticker: kalshiTicker,
                trading_venue: tradingVenue
            })
        });

        const result = await response.json();

        if (!response.ok) {
            alert(`error: ${result.message || 'failed to set trading venue'}`);
        }
    } catch (err) {
        console.error(err);
        alert("connection error");
    }
}

async function setMaxPositionCtx(kalshiTicker) {
    const input = document.getElementById(`ctx-input-${kalshiTicker}`);
    const ctx = parseFloat(input.value);

    if (isNaN(ctx) || ctx < 0) {
        alert("enter a valid ctx value");
        return;
    }

    try {
        const response = await fetch('/set_market_max_position_ctx', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                kalshi_market_ticker: kalshiTicker,
                ctx: ctx,
            })
        });

        const result = await response.json();

        if (!response.ok) {
            alert(`error: ${result.message || 'failed to set max position ctx'}`);
        } else {
            input.value = '';
            input.placeholder = ctx;
        }
    } catch (err) {
        console.error(err);
        alert("connection error");
    }
}