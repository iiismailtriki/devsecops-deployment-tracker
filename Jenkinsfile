pipeline {
    agent {
        label 'devsecops'
    }

    stages {
        stage('Agent Test') {
            steps {
                echo 'Running on the DevSecOps agent!'
                sh 'hostname'
                sh 'pwd'
                sh 'whoami'
                sh 'ls -la'
            }
        }
    }
}
