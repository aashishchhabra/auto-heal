pipeline {
    agent any
    environment {
        VENV = 'venv'
    }
    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        stage('Set up Python') {
            steps {
                sh 'python3 -m venv $VENV'
                sh '. $VENV/bin/activate && pip install --upgrade pip'
                sh '. $VENV/bin/activate && pip install -r requirements.txt pyyaml'
            }
        }
        stage('Lint with flake8') {
            steps {
                sh '. $VENV/bin/activate && pip install flake8 black'
                sh '. $VENV/bin/activate && flake8 src/ tests/'
            }
        }
        stage('Check formatting with black') {
            steps {
                sh '. $VENV/bin/activate && black --check src/ tests/'
            }
        }
        stage('Onboarding/Auto-Discovery Check') {
            steps {
                sh 'chmod +x scripts/check_action_onboarding.py'
                sh '. $VENV/bin/activate && scripts/check_action_onboarding.py'
            }
        }
        stage('Run Tests with Coverage') {
            steps {
                sh '. $VENV/bin/activate && pip install pytest pytest-cov'
                sh '. $VENV/bin/activate && pytest --cov=src --cov-report=xml --cov-report=term --maxfail=1 --disable-warnings -v'
            }
        }
    }
    post {
        always {
            junit '**/test-results.xml'
        }
    }
}
