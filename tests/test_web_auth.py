from django.test import TestCase
from django.contrib.auth import get_user_model


class WebAuthTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='admin2', password='StrongPass123')

    def test_dashboard_requires_login(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_login_dashboard_and_logout_flow(self):
        response = self.client.get('/accounts/login/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '合力数据DDI 管理系统')

        response = self.client.post('/accounts/login/', {'username': 'admin2', 'password': 'StrongPass123', 'next': '/dashboard/'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/dashboard/')

        response = self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '首页仪表盘')
        self.assertContains(response, '合力数据DDI')

        response = self.client.get('/logout/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/accounts/login/')
