// Notification bell polling
let lastCount = 0;

async function fetchUnreadCount() {
    try {
        const res = await fetch('/api/notifications/unread');
        const data = await res.json();
        return data.count || 0;
    } catch (e) {
        return lastCount;
    }
}

async function markAllRead() {
    try {
        await fetch('/api/notifications/mark-read', { method: 'POST' });
    } catch (e) {
        console.error('Failed to mark notifications as read', e);
    }
}

// Update count
async function checkNotifications() {
    const count = await fetchUnreadCount();
    const bell = document.getElementById('notificationCount');
    const bellLink = document.querySelector('.notification-bell');

    if (count > 0) {
        if (bell) bell.textContent = count > 99 ? '99+' : count.toString();
        if (bellLink) bellLink.style.display = 'flex';
    } else {
        if (bell) bell.style.display = 'none';
    }

    lastCount = count;
}

// Mark as read when on notifications page
function markPageNotificationsRead() {
    if (window.location.pathname === '/notifications') {
        markAllRead();
    }
}

// Polling
document.addEventListener('DOMContentLoaded', async () => {
    // First check notifications, THEN mark as read (if on notifications page)
    await checkNotifications();
    markPageNotificationsRead();
    setInterval(checkNotifications, 10000); // Poll every 10 seconds
});
