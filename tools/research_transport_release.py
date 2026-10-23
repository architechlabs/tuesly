"""Read primary ESPHome release notes for relevant transport fixes."""
import json,urllib.request
url='https://api.github.com/repos/esphome/esphome/releases?per_page=6'
request=urllib.request.Request(url,headers={'User-Agent':'Tuesly-maintenance'})
with urllib.request.urlopen(request,timeout=15) as response:releases=json.load(response)
for item in releases:
    print(item['tag_name'],item['published_at'],item['html_url'])
    for line in item.get('body','').splitlines():
        if any(key in line.lower() for key in ('bluetooth','ble_tracker','api','wifi','wi-fi','deadlock','socket','scan','crash')):
            print(line[:400])
