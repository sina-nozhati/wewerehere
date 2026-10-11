# API map (Node legacy → Python)

| Consumer | Endpoint | Notes |
|----------|----------|-------|
| index.html | GET /api/capacity, /api/payment-info, POST /api/orders | Featured event |
| index.html | GET /api/landing | New — dynamic landing |
| track.html | GET /api/events | `isFeatured` per event; ordered by `event_at` desc |
| track.html | GET /api/orders/track | Query: `phone` or `serial`, optional `eventId` (default: featured). Response includes `event` + scoped `orders`/`tickets` |
| admin.html | GET /api/admin/receipts/{orderId} | Bearer required — use fetch+blob in UI, not raw `<img src>` |
| admin.html | /api/admin/* | + /api/admin/events |
| support | /api/support/tickets | Phone-keyed threads |

Removed: POST /api/register → 410 Gone
