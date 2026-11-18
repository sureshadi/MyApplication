// Runs the same test suite on Jenkins. Needs an agent with Docker.
pipeline {
    agent {
        docker {
            image 'mcr.microsoft.com/playwright/python:v1.49.0-noble'
            args '--ipc=host'
        }
    }
    options { timestamps() }
    stages {
        stage('Install') {
            steps {
                sh 'python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt'
            }
        }
        stage('Unit and API tests') {
            steps {
                sh '. .venv/bin/activate && pytest -v --junitxml=test-results/unit-api.xml'
            }
        }
        stage('Browser tests') {
            steps {
                sh '. .venv/bin/activate && python -m playwright install chromium && pytest -m e2e -v --junitxml=test-results/e2e.xml'
            }
        }
    }
    post {
        always {
            junit 'test-results/*.xml'
        }
    }
}
