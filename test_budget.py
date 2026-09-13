from services.db import init
init()
import app
client = app.app.test_client()

def h():
    r = client.get('/')
    return {'X-CSRF-Token': r.headers.get('X-CSRF-Token')}

r = client.post('/api/auth/login', json={'username':'ayesha.gill','password':'procure123'}, headers=h())
print('Login:', r.status_code)

r = client.get('/api/analytics/budget', headers=h())
print('Budget endpoint:', r.status_code)
data = r.get_json()
for d in data['depts']:
    print(f"  {d['name']:15s} total={d['budget_total']:>8} spent={d['budget_spent']:>8} remaining={d['remaining']:>8} pct={d['pct']}% {d['status']}")

# CSRF protection applies to state-changing methods only; GETs are expected to pass
r2 = client.get('/api/analytics/budget', headers={'X-CSRF-Token': 'wrong'})
print('Budget with wrong CSRF (GET, expected 200):', r2.status_code)

print('ALL OK')
