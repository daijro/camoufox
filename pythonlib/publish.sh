rm -rf ./dist
rm -rf ./camoufox/*.mmdb

python -m build
twine check dist/*

read -p "Confirm publish? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    twine upload dist/*
fi
