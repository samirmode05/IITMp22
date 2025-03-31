import os
import unittest
from app import app

class APITestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_home(self):
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'TDS Solver API is running', response.data)

    def test_solve_question_without_question(self):
        response = self.app.post('/api/')
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Question is required', response.data)

    def test_solve_question_with_invalid_file(self):
        response = self.app.post('/api/', data={'question': 'What is the answer?'})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Error processing file', response.data)

    # Additional tests can be added here for file processing and AI interaction

if __name__ == '__main__':
    unittest.main()
