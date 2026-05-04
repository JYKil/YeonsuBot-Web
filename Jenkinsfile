pipeline {
    // 배포 디렉토리 고정 — ./data 볼륨이 이 경로 아래에 영속됨
    agent {
        node {
            label ''
            customWorkspace '/opt/yeonsubot'
        }
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '5'))
        timeout(time: 15, unit: 'MINUTES')
        disableConcurrentBuilds()
        gitLabConnection('gitlab')
    }

    stages {
        stage('준비') {
            steps {
                updateGitlabCommitStatus name: 'jenkins', state: 'running'
                // settings.json 볼륨 마운트 디렉토리 보장
                sh 'mkdir -p data'
            }
        }

        stage('빌드') {
            steps {
                // --pull: 베이스 이미지 최신화, 레이어 캐시는 유지
                sh 'docker compose build --pull'
            }
        }

        stage('배포') {
            steps {
                sh 'docker compose up -d --force-recreate --remove-orphans'
            }
        }

        stage('헬스체크') {
            steps {
                script {
                    // 컨테이너 기동 + Playwright 초기화 대기
                    sleep(time: 20, unit: 'SECONDS')
                    sh 'curl -fsS http://192.168.75.205:3000/api/status'
                }
            }
        }
    }

    post {
        success {
            updateGitlabCommitStatus name: 'jenkins', state: 'success'
        }
        failure {
            updateGitlabCommitStatus name: 'jenkins', state: 'failed'
            // 실패 시 컨테이너 로그 출력 (Jenkins 빌드 로그에서 확인)
            sh 'docker compose logs --tail=100 || true'
        }
        aborted {
            updateGitlabCommitStatus name: 'jenkins', state: 'canceled'
        }
        always {
            // 댕글링 이미지 정리
            sh 'docker image prune -f || true'
        }
    }
}
