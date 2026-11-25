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
                sh 'rm -rf coverage-data coverage-report && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt'
            }
        }
        stage('Unit and API tests') {
            steps {
                sh '. .venv/bin/activate && COVERAGE_FILE=coverage-data/unit-api.cov pytest -v --junitxml=test-results/unit-api.xml --cov --cov-report='
            }
        }
        stage('Browser tests') {
            steps {
                sh '. .venv/bin/activate && python -m playwright install chromium && COVERAGE_FILE=coverage-data/e2e.cov pytest -m e2e -v --junitxml=test-results/e2e.xml --cov --cov-report='
            }
        }
    }
    post {
        always {
            junit 'test-results/*.xml'
            // One coverage report for unit, API and browser tests: the total is printed in the console log,
            // and the HTML report is kept with the build (Build → Artifacts → coverage-report/html/index.html).
            sh '. .venv/bin/activate && ./scripts/coverage.sh report || true'
            archiveArtifacts artifacts: 'coverage-report/**', allowEmptyArchive: true
        }
    }
}
