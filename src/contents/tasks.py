import requests
from contentapi.celery import app

@app.task(queue="content_pull")
def pull_and_store_content():
    # TODO: The design of this celery task is very weird. It's posting the response to localhost:3000.
    #  which is not ideal
    url = "https://hackapi.hellozelf.com/api/v1/contents/"

    headers = {
        'x-api-key': '05825ac5sk_d10esk_42bcsk_9999sk_94c3dea310db1728067022'
    }
    api_url = "http://localhost:3000/api/contents/"
    res = requests.get(url, headers=headers, timeout=20).json()
    for item in res:
        payload = {**item}
        requests.post(api_url, json=payload, timeout=20)


@app.task(queue='generate_ai_comment')
def ai_generated_comment():
    url = 'https://hackapi.hellozelf.com/api/v1/ai_comment/'
    headers = {
        'x-api-key': '05825ac5sk_d10esk_42bcsk_9999sk_94c3dea310db1728067022'
    }
    res = requests.get(url, headers=headers, timeout=20).json()
    post_comment_payload = {
        'content_id': res.get('content_id'),
        'comment_text': res.get('comment_text')
    }

    post_url = 'https://hackapi.hellozelf.com/api/v1/comment/'
    post_res = requests.post(post_url,
                             headers=headers,
                             data=post_comment_payload, timeout=20)
