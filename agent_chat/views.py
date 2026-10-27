from django.views import View
from django.shortcuts import render

class ChatView(View):
    template_name = "chat.html"

    def get(self, request):
        return render(request, self.template_name)